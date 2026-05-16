from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException, Response

from backend import config
from backend.api import routes
from backend.db import database
from backend.services import auth_service, local_agent_service
from backend.services.gst_invoice import IMPORT_TYPE_GST
from backend.services.sync_service import sync_from_tally
from backend.services.tally_client import TallyError


class Parent2FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database.init_db()
        self.original_allow_dev_auth = config.ALLOW_DEV_AUTH
        config.ALLOW_DEV_AUTH = True
        self.addCleanup(lambda: setattr(config, "ALLOW_DEV_AUTH", self.original_allow_dev_auth))
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

    def make_agent(self) -> dict:
        database.create_pairing_token(self.user["id"], "Office PC", "hash", base_url="http://localhost:9100")
        return database.pair_local_agent("hash", base_url="http://localhost:9100")

    def company_request(self, company_name: str = "Bhrama Enterprises") -> routes.CompanyRequest:
        return routes.CompanyRequest(
            company_name=company_name,
            supplier_gstin="29AAECP4424C1ZN",
            supplier_state="Karnataka",
        )

    def fake_master_dispatch(self, agent_arg, operation, payload):
        if operation == "health_check":
            return {"status": "connected"}
        if operation == "list_companies":
            return {"companies": ["Bhrama Enterprises", "Company B"]}
        if operation == "export_collection" and payload["collection_id"] == "Ledger":
            return {"ledgers": [{"name": "Sales", "group": "Sales Accounts"}, {"name": "Cash", "group": "Cash-in-Hand"}]}
        if operation == "export_collection" and payload["collection_id"] == "StockItem":
            return {"stock_items": ["2.75-18 NGP"]}
        if operation == "create_sales_voucher":
            return {"STATUS": "1"}
        return {}

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

    def test_dev_auth_is_rejected_unless_enabled(self) -> None:
        config.ALLOW_DEV_AUTH = False
        with self.assertRaises(HTTPException) as raised:
            auth_service.create_login_session("test:new@example.test", Response())
        self.assertEqual(raised.exception.status_code, 401)

    def test_logout_accepts_route_call_without_cookie_dependency_default(self) -> None:
        class Request:
            cookies: dict[str, str] = {}
            headers: dict[str, str] = {}

        response = Response()
        auth_service.logout(Request(), response)

        self.assertIn(auth_service.SESSION_COOKIE, response.headers["set-cookie"])

    def test_logout_revokes_cookie_session(self) -> None:
        response = Response()
        auth_service.create_login_session("test:logout@example.test", response)
        cookie = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]

        class Request:
            cookies = {auth_service.SESSION_COOKIE: cookie}
            headers: dict[str, str] = {}

        auth_service.logout(Request(), Response())

        self.assertIsNone(database.get_session_by_hash(auth_service.hash_token(cookie)))

    def test_user_scoped_agent_pairing_token_returns_one_time_connector_secret(self) -> None:
        pairing = routes.create_user_agent_pairing_token(
            routes.PairingTokenRequest(device_name="Office Connector", base_url="https://connector.example.test"),
            user=self.user,
        )

        self.assertIn("pairing_token", pairing)
        self.assertIn("agent_auth_token", pairing)
        self.assertNotIn("auth_token", pairing["agent"])

        paired = routes.pair_agent(
            routes.PairAgentRequest(
                pairing_token=pairing["pairing_token"],
                device_name="Office Connector",
                base_url="https://connector.example.test",
            )
        )
        self.assertEqual(paired["agent"]["pairing_status"], "paired")
        self.assertNotIn("auth_token", paired["agent"])

        stored = database.get_local_agent(pairing["agent"]["id"], user_id=self.user["id"])
        self.assertEqual(stored["auth_token"], pairing["agent_auth_token"])

    def test_legacy_prototype_endpoints_can_be_disabled_for_production(self) -> None:
        original = config.LEGACY_ENDPOINTS_ENABLED
        config.LEGACY_ENDPOINTS_ENABLED = False
        self.addCleanup(lambda: setattr(config, "LEGACY_ENDPOINTS_ENABLED", original))

        with self.assertRaises(HTTPException) as raised:
            routes.sync()

        self.assertEqual(raised.exception.status_code, 404)

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

    def test_init_db_migrates_legacy_global_master_uniqueness(self) -> None:
        with database.get_connection() as connection:
            connection.executescript(
                """
                DROP TABLE stock_items;
                DROP TABLE ledgers;
                CREATE TABLE stock_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    company_id INTEGER
                );
                CREATE TABLE ledgers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    "group" TEXT,
                    company_id INTEGER
                );
                """
            )

        first = self.make_company(company_name="Company A")
        second = self.make_company(company_name="Company B")
        database.init_db()

        database.replace_stock_items(["Keyboard", "Monitor"], company_id=first["id"])
        database.replace_stock_items(["Keyboard", "Mouse"], company_id=second["id"])
        database.replace_ledgers([{"name": "Sales", "group": "Sales Accounts"}], company_id=first["id"])
        database.replace_ledgers([{"name": "Sales", "group": "Direct Incomes"}], company_id=second["id"])

        self.assertEqual({item["name"] for item in database.list_stock_items(first["id"])}, {"Keyboard", "Monitor"})
        self.assertEqual({item["name"] for item in database.list_stock_items(second["id"])}, {"Keyboard", "Mouse"})
        self.assertEqual(database.get_ledger_by_name("Sales", first["id"])["group"], "Sales Accounts")
        self.assertEqual(database.get_ledger_by_name("Sales", second["id"])["group"], "Direct Incomes")

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

    def test_create_company_validates_tally_before_persisting(self) -> None:
        self.make_agent()
        with patch(
            "backend.services.local_agent_service.dispatch_tally_operation",
            side_effect=self.fake_master_dispatch,
        ) as dispatch:
            created = routes.create_company(
                self.company_request(),
                user=self.user,
            )

        self.assertEqual(created["company"]["company_name"], "Bhrama Enterprises")
        self.assertIsNotNone(created["company"]["local_agent_id"])
        self.assertEqual(created["sync"]["last_sync_status"], "success")
        self.assertEqual(routes.list_companies(user=self.user)["active_company_id"], created["company"]["id"])
        self.assertTrue(any(call.args[2].get("company_name") == "Bhrama Enterprises" for call in dispatch.call_args_list if call.args[1] == "export_collection"))

        with self.assertRaises(HTTPException) as raised:
            routes.create_company(self.company_request("bhrama enterprises"), user=self.user)
        self.assertEqual(raised.exception.status_code, 409)

    def test_create_company_requires_company_gst_details(self) -> None:
        with self.assertRaises(HTTPException) as missing_gstin:
            routes.create_company(
                routes.CompanyRequest(company_name="Bhrama Enterprises", supplier_state="Karnataka"),
                user=self.user,
            )
        self.assertEqual(missing_gstin.exception.status_code, 400)
        self.assertEqual(missing_gstin.exception.detail, "Company GSTIN is required")

        with self.assertRaises(HTTPException) as invalid_gstin:
            routes.create_company(
                routes.CompanyRequest(company_name="Bhrama Enterprises", supplier_gstin="invalid", supplier_state="Karnataka"),
                user=self.user,
            )
        self.assertEqual(invalid_gstin.exception.status_code, 400)
        self.assertEqual(invalid_gstin.exception.detail, "Company GSTIN must be a valid GSTIN")

        with self.assertRaises(HTTPException) as missing_state:
            routes.create_company(
                routes.CompanyRequest(company_name="Bhrama Enterprises", supplier_gstin="29AAECP4424C1ZN"),
                user=self.user,
            )
        self.assertEqual(missing_state.exception.status_code, 400)
        self.assertEqual(missing_state.exception.detail, "Company GST state is required")
        self.assertEqual(database.list_companies(self.user["id"]), [])

    def test_create_company_blocks_missing_or_unreachable_tally_company(self) -> None:
        self.make_agent()

        def missing_company(agent_arg, operation, payload):
            if operation == "health_check":
                return {"status": "connected"}
            return {"ledgers": []}

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=missing_company):
            with self.assertRaises(HTTPException) as missing:
                routes.create_company(self.company_request("Missing Company"), user=self.user)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(database.list_companies(self.user["id"]), [])

        with patch(
            "backend.services.local_agent_service.dispatch_tally_operation",
            side_effect=TallyError("Local agent request failed: Tally request failed: connection refused"),
        ):
            with self.assertRaises(HTTPException) as unreachable:
                routes.create_company(self.company_request(), user=self.user)
        self.assertEqual(unreachable.exception.status_code, 503)
        self.assertIn("Can't connect to Tally", unreachable.exception.detail)

    def test_tally_status_and_company_discovery_are_backend_owned(self) -> None:
        self.make_agent()
        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=self.fake_master_dispatch):
            status = routes.tally_status(user=self.user)
            companies = routes.tally_companies(user=self.user)

        self.assertEqual(status["status"], "connected")
        self.assertEqual(companies["companies"], ["Bhrama Enterprises", "Company B"])

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
        agent = self.make_agent()
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

    def test_company_sync_persists_detailed_stock_items_for_inventory_screen(self) -> None:
        company = self.make_company()
        agent = self.make_agent()
        database.update_company(company["id"], self.user["id"], {"local_agent_id": agent["id"]})

        def fake_dispatch(agent_arg, operation, payload):
            if payload["collection_id"] == "Ledger":
                return {"ledgers": [{"name": "Sales", "group": "Sales Accounts"}]}
            return {
                "stock_items": [
                    {
                        "name": "Apple MacBook Pro Laptop",
                        "group_name": "Laptops",
                        "category": "Finished Goods",
                        "base_unit": "Nos",
                        "opening_balance": "10 Nos",
                        "closing_balance": "4 Nos",
                        "closing_value": "400000.00",
                        "gst_type": "Goods",
                        "gst_rate": 18,
                        "raw": {"NAME": "Apple MacBook Pro Laptop"},
                    }
                ]
            }

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=fake_dispatch):
            routes.company_sync(company["id"], user=self.user)

        response = routes.company_stock_items(company["id"], user=self.user)
        item = response["items"][0]
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["low_stock_count"], 1)
        self.assertEqual(response["groups"], ["Laptops"])
        self.assertEqual(item["base_unit"], "Nos")
        self.assertEqual(item["gst_rate"], 18)
        self.assertEqual(item["raw"], {"NAME": "Apple MacBook Pro Laptop"})

    def test_import_rows_persist_and_process_validates_company_masters(self) -> None:
        company = self.make_company()
        self.seed_company_masters(company)
        import_record = self.upload_rows(company)

        result = routes.process_import(company["id"], import_record["id"], user=self.user)

        self.assertEqual(result["import"]["valid_count"], 1)
        self.assertEqual(result["rows"][0]["validation_status"], "valid")
        self.assertEqual(result["rows"][0]["voucher_preview"]["Date"], "2026-05-04")

    def test_gst_import_preview_calculates_same_state_tax_totals(self) -> None:
        company = self.make_company()
        database.update_company(
            company["id"],
            self.user["id"],
            {"supplier_gstin": "29AAECP4424C1ZN", "supplier_state": "Karnataka"},
        )
        company = database.get_company(company["id"], user_id=self.user["id"])
        database.replace_stock_items(
            [
                {
                    "name": "GST Coffee",
                    "base_unit": "nos",
                    "gst_rate": 5,
                    "taxability": "Taxable",
                    "gst_type": "Goods",
                }
            ],
            company_id=company["id"],
        )
        rows = [
            {
                "product_name": "GST Coffee",
                "quantity": 20,
                "rate": 75,
                "price": 75,
                "payment_mode": "Bank Transfer",
                "voucher_date": "2026-03-01",
                "buyer_name": "Chanda Enterprises",
                "buyer_gstin": "29AAACH1004N1ZQ",
                "buyer_state": "Karnataka",
                "source_row_id": "2",
            }
        ]
        import_record = database.create_import(self.user["id"], company["id"], "gst-sales.xlsx", rows, import_type=IMPORT_TYPE_GST)

        result = routes.process_import(company["id"], import_record["id"], user=self.user)

        row = result["rows"][0]
        self.assertEqual(result["import"]["import_type"], IMPORT_TYPE_GST)
        self.assertEqual(row["validation_status"], "valid")
        self.assertEqual(row["taxable_amount"], 1500)
        self.assertEqual(row["cgst_amount"], 37.5)
        self.assertEqual(row["sgst_amount"], 37.5)
        self.assertEqual(row["igst_amount"], 0)
        self.assertEqual(row["total_amount"], 1575)
        self.assertEqual(row["voucher_preview"]["VoucherKind"], IMPORT_TYPE_GST)

    def test_gst_import_commit_creates_required_ledgers_and_dispatches_gst_voucher(self) -> None:
        company = self.make_company()
        agent = self.make_agent()
        database.update_company(
            company["id"],
            self.user["id"],
            {
                "local_agent_id": agent["id"],
                "supplier_gstin": "29AAECP4424C1ZN",
                "supplier_state": "Karnataka",
            },
        )
        company = database.get_company(company["id"], user_id=self.user["id"])
        database.replace_stock_items(
            [{"name": "GST Coffee", "base_unit": "nos", "gst_rate": 5, "hsn_code": "4820", "taxability": "Taxable"}],
            company_id=company["id"],
        )
        database.replace_ledgers([{"name": "Cash", "group": "Cash-in-Hand"}], company_id=company["id"])
        import_record = database.create_import(
            self.user["id"],
            company["id"],
            "gst-sales.xlsx",
            [
                {
                    "product_name": "GST Coffee",
                    "quantity": 20,
                    "rate": 75,
                    "price": 75,
                    "payment_mode": "Bank Transfer",
                    "voucher_date": "2026-03-01",
                    "buyer_name": "Chanda Enterprises",
                    "buyer_gstin": "29AAACH1004N1ZQ",
                    "buyer_state": "Karnataka",
                    "source_row_id": "2",
                }
            ],
            import_type=IMPORT_TYPE_GST,
        )
        routes.process_import(company["id"], import_record["id"], user=self.user)
        created_ledgers: list[str] = []
        dispatched_vouchers: list[dict] = []

        def fake_dispatch(agent_arg, operation, payload):
            if operation == "health_check":
                return {"status": "connected"}
            if operation == "create_ledger":
                created_ledgers.append(payload["name"])
                return {"STATUS": "1"}
            if operation == "create_sales_voucher":
                dispatched_vouchers.append(payload["voucher"])
                return {"STATUS": "1"}
            return self.fake_master_dispatch(agent_arg, operation, payload)

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=fake_dispatch):
            committed = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)

        self.assertEqual(committed["success_count"], 1)
        self.assertEqual(set(created_ledgers), {"GST Sales", "Chanda Enterprises", "CGST", "SGST"})
        self.assertEqual(dispatched_vouchers[0]["VoucherKind"], IMPORT_TYPE_GST)
        self.assertEqual(dispatched_vouchers[0]["InvoiceTotal"], 1575)

    def test_company_upi_rows_preview_and_create_fallback_ledger_on_commit(self) -> None:
        company = self.make_company()
        agent = self.make_agent()
        database.update_company(company["id"], self.user["id"], {"local_agent_id": agent["id"]})
        self.seed_company_masters(company, include_upi=False)
        rows = [
            {
                "product_name": "2.75-18 NGP",
                "price": 1600,
                "payment_mode": "UPI",
                "voucher_date": "2026-05-04",
                "source_row_id": "2",
            }
        ]
        import_record = database.create_import(self.user["id"], company["id"], "sales.xlsx", rows)
        processed = routes.process_import(company["id"], import_record["id"], user=self.user)

        operations: list[str] = []

        def fake_dispatch(agent_arg, operation, payload):
            operations.append(operation)
            if operation == "health_check":
                return {"status": "connected"}
            if operation == "create_ledger":
                self.assertEqual(payload["name"], "UPI Sales")
                self.assertEqual(payload["company_name"], "Bhrama Enterprises")
                return {"STATUS": "1"}
            if operation == "create_sales_voucher":
                return {"STATUS": "1"}
            return self.fake_master_dispatch(agent_arg, operation, payload)

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=fake_dispatch):
            committed = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)

        self.assertEqual(processed["import"]["valid_count"], 1)
        self.assertEqual(processed["rows"][0]["validation_status"], "valid")
        self.assertEqual(committed["success_count"], 1)
        self.assertIn("create_ledger", operations)
        self.assertIsNotNone(database.get_ledger_by_name("UPI Sales", company_id=company["id"]))

    def test_missing_configured_ledgers_are_created_on_commit(self) -> None:
        company = self.make_company()
        agent = self.make_agent()
        database.update_company(
            company["id"],
            self.user["id"],
            {
                "local_agent_id": agent["id"],
                "sales_ledger_name": "Retail Sales",
                "sales_ledger_group_name": "Sales Accounts",
                "payment_default_group_name": "Sundry Debtors",
                "payment_ledger_mappings": {
                    "card": {"ledger_name": "Card Collections", "group_name": "Bank Accounts"},
                },
            },
        )
        company = database.get_company(company["id"], user_id=self.user["id"])
        database.replace_stock_items(["2.75-18 NGP"], company_id=company["id"])
        database.replace_ledgers([{"name": "Existing Ledger", "group": "Current Assets"}], company_id=company["id"])
        database.set_company_sync(company["id"], "success", database.utc_now())
        rows = [
            {
                "product_name": "2.75-18 NGP",
                "price": 1600,
                "payment_mode": "Card",
                "voucher_date": "2026-05-04",
                "source_row_id": "2",
            }
        ]
        import_record = database.create_import(self.user["id"], company["id"], "sales.xlsx", rows)
        processed = routes.process_import(company["id"], import_record["id"], user=self.user)

        created_ledgers: list[tuple[str, str]] = []

        def fake_dispatch(agent_arg, operation, payload):
            if operation == "health_check":
                return {"status": "connected"}
            if operation == "create_ledger":
                created_ledgers.append((payload["name"], payload["group_name"]))
                return {"STATUS": "1"}
            if operation == "create_sales_voucher":
                return {"STATUS": "1"}
            return self.fake_master_dispatch(agent_arg, operation, payload)

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=fake_dispatch):
            committed = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)

        self.assertEqual(processed["import"]["valid_count"], 1)
        self.assertEqual(committed["success_count"], 1)
        self.assertEqual(created_ledgers, [("Retail Sales", "Sales Accounts"), ("Card Collections", "Bank Accounts")])
        self.assertIsNotNone(database.get_ledger_by_name("Retail Sales", company_id=company["id"]))
        self.assertIsNotNone(database.get_ledger_by_name("Card Collections", company_id=company["id"]))

    def test_commit_import_rows_through_local_agent_and_blocks_duplicates(self) -> None:
        company = self.make_company()
        agent = self.make_agent()
        database.update_company(company["id"], self.user["id"], {"local_agent_id": agent["id"]})
        self.seed_company_masters(company)
        import_record = self.upload_rows(company)
        routes.process_import(company["id"], import_record["id"], user=self.user)

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=self.fake_master_dispatch):
            first = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)
            second = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)

        self.assertEqual(first["success_count"], 1)
        self.assertEqual(second["success_count"], 0)
        logs = database.list_voucher_logs(company["id"])
        self.assertEqual(logs[0]["user_id"], self.user["id"])
        self.assertEqual(logs[0]["company_id"], company["id"])
        self.assertEqual(logs[0]["import_id"], import_record["id"])

    def test_duplicate_looking_rows_are_allowed_in_import_path(self) -> None:
        company = self.make_company()
        agent = self.make_agent()
        database.update_company(company["id"], self.user["id"], {"local_agent_id": agent["id"]})
        self.seed_company_masters(company)
        rows = [
            {
                "product_name": "2.75-18 NGP",
                "price": 1600,
                "payment_mode": "Cash",
                "voucher_date": "2026-05-04",
                "source_row_id": "2",
            },
            {
                "product_name": "2.75-18 NGP",
                "price": 1600,
                "payment_mode": "Cash",
                "voucher_date": "2026-05-04",
                "source_row_id": "3",
            },
        ]
        import_record = database.create_import(self.user["id"], company["id"], "sales.xlsx", rows)
        processed = routes.process_import(company["id"], import_record["id"], user=self.user)

        with patch("backend.services.local_agent_service.dispatch_tally_operation", side_effect=self.fake_master_dispatch):
            committed = routes.commit_import(company["id"], import_record["id"], routes.CommitRequest(), user=self.user)

        self.assertEqual(processed["import"]["valid_count"], 2)
        self.assertEqual(committed["success_count"], 2)

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
