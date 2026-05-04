from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException, Response

from backend.api import routes
from backend.db import database
from backend.services import auth_service, local_agent_service
from backend.services.sync_service import sync_from_tally


class Parent2FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database.init_db()
        self.user = database.create_or_update_user("user-1", "owner@example.test", "Owner")
        self.other_user = database.create_or_update_user("user-2", "other@example.test", "Other")

    def make_company(self, user_id: int | None = None, company_name: str = "Bhrama Enterprises") -> dict:
        return database.create_company(
            user_id or self.user["id"],
            {
                "company_name": company_name,
                "tally_url": "http://localhost:9000",
                "sales_ledger_name": "Sales",
                "cash_ledger_name": "Cash",
                "upi_fallback_ledger_name": "UPI Sales",
                "upi_fallback_group_name": "Sundry Debtors",
            },
        )

    def seed_company_masters(self, company: dict, include_upi: bool = True) -> None:
        ledgers = [
            {"name": "Cash", "group": "Cash-in-Hand"},
            {"name": "Sales", "group": "Sales Accounts"},
        ]
        if include_upi:
            ledgers.append({"name": "UPI Sales", "group": "Sundry Debtors"})
        database.replace_ledgers(ledgers, company_id=company["id"])
        database.replace_stock_items(["2.75-18 NGP"], company_id=company["id"])
        database.set_company_sync(company["id"], "success", database.utc_now())

    def upload_rows(self, company: dict) -> dict:
        rows = [
            {
                "product_name": "2.75-18 NGP",
                "price": 1600,
                "payment_mode": "Cash",
                "voucher_date": "2026-05-04",
                "source_row_id": "2",
            }
        ]
        return database.create_import(self.user["id"], company["id"], "sales.xlsx", rows)

    def test_auth_service_creates_user_and_server_side_session(self) -> None:
        response = Response()
        user = auth_service.create_login_session("test:new@example.test", response)

        self.assertEqual(user["email"], "new@example.test")
        cookie = response.headers["set-cookie"]
        self.assertIn(auth_service.SESSION_COOKIE, cookie)

    def test_company_scoped_masters_allow_same_names(self) -> None:
        first = self.make_company(company_name="Company A")
        second = self.make_company(company_name="Company B")

        database.replace_ledgers([{"name": "Sales", "group": "Sales Accounts"}], company_id=first["id"])
        database.replace_ledgers([{"name": "Sales", "group": "Direct Incomes"}], company_id=second["id"])
        database.replace_stock_items(["2.75-18 NGP"], company_id=first["id"])
        database.replace_stock_items(["2.75-18 NGP"], company_id=second["id"])

        self.assertEqual(database.get_ledger_by_name("Sales", first["id"])["group"], "Sales Accounts")
        self.assertEqual(database.get_ledger_by_name("Sales", second["id"])["group"], "Direct Incomes")
        self.assertEqual(len(database.list_stock_items(first["id"])), 1)
        self.assertEqual(len(database.list_stock_items(second["id"])), 1)

    def test_company_crud_enforces_ownership_and_invalidates_masters(self) -> None:
        company = self.make_company()
        self.seed_company_masters(company)

        with self.assertRaises(HTTPException):
            routes.get_company(company["id"], user=self.other_user)

        updated = routes.update_company(
            company["id"],
            routes.CompanyUpdateRequest(tally_url="http://localhost:9001"),
            user=self.user,
        )["company"]

        self.assertEqual(updated["last_sync_status"], "invalidated")
        self.assertEqual(database.list_ledgers(company["id"]), [])

    def test_local_agent_pairing_heartbeat_and_revocation(self) -> None:
        company = self.make_company()

        pairing = routes.create_agent_pairing_token(
            company["id"],
            routes.PairingTokenRequest(device_name="Office PC", base_url="http://localhost:9100"),
            user=self.user,
        )
        paired = routes.pair_agent(
            routes.PairAgentRequest(
                pairing_token=pairing["pairing_token"],
                device_name="Office PC",
                base_url="http://localhost:9100",
            )
        )["agent"]
        heartbeat = routes.heartbeat_agent(routes.HeartbeatRequest(agent_id=paired["id"]))["agent"]

        self.assertEqual(heartbeat["pairing_status"], "paired")
        self.assertTrue(routes.revoke_agent(company["id"], paired["id"], user=self.user))

    def test_company_sync_uses_local_agent_and_company_scope(self) -> None:
        company = self.make_company()
        agent = database.create_pairing_token(self.user["id"], "Office PC", "hash", base_url="http://localhost:9100")
        agent = database.pair_local_agent("hash", base_url="http://localhost:9100")
        database.update_company(company["id"], self.user["id"], {"local_agent_id": agent["id"]})

        def fake_dispatch(agent_arg, operation, payload):
            self.assertEqual(payload["company_name"], "Bhrama Enterprises")
            if payload["collection_id"] == "Ledger":
                return {"ledgers": [{"name": "Sales", "group": "Sales Accounts"}, {"name": "Cash", "group": "Cash-in-Hand"}]}
            return {"stock_items": ["2.75-18 NGP"]}

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=fake_dispatch):
            result = routes.company_sync(company["id"], user=self.user)

        self.assertEqual(result["last_sync_status"], "success")
        self.assertEqual(len(database.list_ledgers(company["id"])), 2)
        self.assertEqual(len(database.list_stock_items(company["id"])), 1)

    def test_import_rows_persist_and_process_validates_company_masters(self) -> None:
        company = self.make_company()
        self.seed_company_masters(company)
        import_record = self.upload_rows(company)

        result = routes.process_import(company["id"], import_record["id"], user=self.user)

        self.assertEqual(result["import"]["valid_count"], 1)
        self.assertEqual(result["rows"][0]["validation_status"], "valid")
        self.assertEqual(result["rows"][0]["voucher_preview"]["Date"], "2026-05-04")

    def test_commit_import_rows_through_local_agent_and_blocks_duplicates(self) -> None:
        company = self.make_company()
        agent = database.create_pairing_token(self.user["id"], "Office PC", "hash", base_url="http://localhost:9100")
        agent = database.pair_local_agent("hash", base_url="http://localhost:9100")
        database.update_company(company["id"], self.user["id"], {"local_agent_id": agent["id"]})
        self.seed_company_masters(company)
        import_record = self.upload_rows(company)
        routes.process_import(company["id"], import_record["id"], user=self.user)

        with patch("backend.services.local_agent_service.dispatch_tally_operation", return_value={"STATUS": "1"}):
            first = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)
            second = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)

        self.assertEqual(first["success_count"], 1)
        self.assertEqual(second["success_count"], 0)
        logs = database.list_voucher_logs(company["id"])
        self.assertEqual(logs[0]["user_id"], self.user["id"])
        self.assertEqual(logs[0]["company_id"], company["id"])
        self.assertEqual(logs[0]["import_id"], import_record["id"])

    def test_excel_upload_contract_still_requires_voucher_date(self) -> None:
        buffer = BytesIO()
        pd.DataFrame([{"product_name": "2.75-18 NGP", "price": 1600, "payment_mode": "Cash"}]).to_excel(
            buffer,
            index=False,
        )

        with self.assertRaises(Exception):
            # Parser-level assertion keeps this independent from async upload plumbing.
            from backend.services.excel_parser import parse_excel

            parse_excel(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
