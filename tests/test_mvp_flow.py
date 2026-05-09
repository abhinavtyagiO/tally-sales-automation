from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import requests
from fastapi import HTTPException

from backend.api import routes
from backend.db import database
from backend.services import voucher_builder
from backend.services.excel_parser import ExcelParseError, parse_excel
from backend.services.sync_service import get_cache_snapshot, sync_from_tally
from backend.services.tally_client import TallyClient, TallyError


class FakeTally:
    def __init__(self) -> None:
        self.created_ledgers = []
        self.created_vouchers = []

    def get_all_ledgers(self):
        return [
            {"name": "Cash", "group": "Cash-in-Hand"},
            {"name": "Sales", "group": "Sales Accounts"},
        ]

    def get_all_stock_items(self):
        return ["2.75-18 NGP"]

    def get_company_name(self):
        return "Test Company"

    def create_ledger(self, name, group_name):
        self.created_ledgers.append((name, group_name))
        return {"STATUS": "1"}

    def create_sales_voucher(self, voucher):
        self.created_vouchers.append(voucher)
        return {"STATUS": "1"}


class MvpFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database.init_db()

    def seed_cache(self, include_upi: bool = True) -> None:
        ledgers = [
            {"name": "Cash", "group": "Cash-in-Hand"},
            {"name": "Sales", "group": "Sales Accounts"},
        ]
        if include_upi:
            ledgers.append({"name": "UPI Sales", "group": "Sundry Debtors"})
        database.replace_ledgers(ledgers)
        database.replace_stock_items(["2.75-18 NGP"])
        database.set_metadata("last_sync_at", datetime.now(timezone.utc).isoformat())
        database.set_metadata("last_sync_status", "success")

    def test_excel_parser_requires_and_propagates_voucher_date(self) -> None:
        buffer = BytesIO()
        pd.DataFrame(
            [
                {
                    "product_name": "2.75-18 NGP",
                    "price": 1600,
                    "payment_mode": "Cash",
                    "voucher_date": "2026-05-04",
                }
            ]
        ).to_excel(buffer, index=False)

        rows = parse_excel(buffer.getvalue())

        self.assertEqual(rows[0]["voucher_date"], "2026-05-04")
        self.assertEqual(rows[0]["source_row_id"], "2")

    def test_excel_parser_accepts_configurable_payment_modes(self) -> None:
        buffer = BytesIO()
        pd.DataFrame(
            [
                {
                    "product_name": "2.75-18 NGP",
                    "price": 1600,
                    "payment_mode": "Card",
                    "voucher_date": "2026-05-04",
                }
            ]
        ).to_excel(buffer, index=False)

        rows = parse_excel(buffer.getvalue())

        self.assertEqual(rows[0]["payment_mode"], "card")

    def test_excel_parser_rejects_missing_voucher_date(self) -> None:
        buffer = BytesIO()
        pd.DataFrame([{"product_name": "2.75-18 NGP", "price": 1600, "payment_mode": "Cash"}]).to_excel(
            buffer,
            index=False,
        )

        with self.assertRaisesRegex(ExcelParseError, "Missing required columns: voucher_date"):
            parse_excel(buffer.getvalue())

    def test_process_builds_voucher_with_date_and_configured_sales_ledger(self) -> None:
        self.seed_cache()
        result = routes.process_rows(
            routes.ProcessRequest(
                import_id="import-1",
                rows=[
                    routes.SaleRow(
                        product_name="2.75-18 NGP",
                        price=1600,
                        payment_mode="Cash",
                        voucher_date="2026-05-04",
                    )
                ],
            )
        )

        voucher = result["vouchers"][0]
        self.assertEqual(voucher["Date"], "2026-05-04")
        self.assertEqual(voucher["LedgerEntries"][0]["LedgerName"], "Sales")
        self.assertEqual(result["ready_count"], 1)

    def test_process_reports_row_level_validation_errors(self) -> None:
        self.seed_cache(include_upi=False)
        result = routes.process_rows(
            routes.ProcessRequest(
                rows=[
                    routes.SaleRow(product_name="Unknown", price=1600, payment_mode="Cash", voucher_date="2026-05-04"),
                    routes.SaleRow(product_name="2.75-18 NGP", price=1600, payment_mode="UPI", voucher_date="2026-05-04"),
                ]
            )
        )

        self.assertEqual(result["ready_count"], 0)
        self.assertEqual(result["skipped_count"], 2)
        self.assertIn("Product not found", result["errors"][0]["error"])
        self.assertIn("UPI Sales", result["errors"][1]["error"])

    def test_process_requires_master_cache(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            routes.process_rows(
                routes.ProcessRequest(
                    rows=[
                        routes.SaleRow(
                            product_name="2.75-18 NGP",
                            price=1600,
                            payment_mode="Cash",
                            voucher_date="2026-05-04",
                        )
                    ]
                )
            )

        self.assertIn("Run /sync first", raised.exception.detail)

    def test_process_rejects_stale_master_cache(self) -> None:
        self.seed_cache()
        database.set_metadata("last_sync_at", (datetime.now(timezone.utc) - timedelta(days=3)).isoformat())

        with self.assertRaises(HTTPException) as raised:
            routes.process_rows(
                routes.ProcessRequest(
                    rows=[
                        routes.SaleRow(
                            product_name="2.75-18 NGP",
                            price=1600,
                            payment_mode="Cash",
                            voucher_date="2026-05-04",
                        )
                    ]
                )
            )

        self.assertIn("stale", raised.exception.detail)

    def test_sync_records_cache_freshness(self) -> None:
        sync_from_tally(FakeTally())
        snapshot = get_cache_snapshot()

        self.assertEqual(snapshot["last_sync_status"], "success")
        self.assertIsNotNone(snapshot["last_sync_at"])
        self.assertEqual(len(snapshot["ledgers"]), 2)

    def test_commit_creates_upi_fallback_and_logs_source_metadata(self) -> None:
        self.seed_cache(include_upi=False)
        fake = FakeTally()

        with patch("backend.api.routes.TallyClient", return_value=fake), patch(
            "backend.services.voucher_builder.TallyClient",
            return_value=fake,
        ):
            result = routes.commit(
                routes.CommitRequest(
                    import_id="import-1",
                    rows=[
                        routes.SaleRow(
                            product_name="2.75-18 NGP",
                            price=1600,
                            payment_mode="UPI",
                            voucher_date="2026-05-04",
                        )
                    ],
                )
            )

        self.assertEqual(result["success_count"], 1)
        self.assertEqual(fake.created_ledgers, [("UPI Sales", "Sundry Debtors")])
        logs = database.list_voucher_logs()
        self.assertTrue(any(log["source_fingerprint"] for log in logs if log["status"] == "success"))

    def test_commit_allows_duplicate_source_rows(self) -> None:
        self.seed_cache()
        fake = FakeTally()
        request = routes.CommitRequest(
            import_id="import-1",
            rows=[
                routes.SaleRow(
                    product_name="2.75-18 NGP",
                    price=1600,
                    payment_mode="Cash",
                    voucher_date="2026-05-04",
                    source_row_id="2",
                )
            ],
        )

        with patch("backend.api.routes.TallyClient", return_value=fake):
            first = routes.commit(request)
            self.assertEqual(first["success_count"], 1)
            duplicate = routes.commit(request)

        self.assertEqual(duplicate["success_count"], 1)

    def test_tally_client_accepts_xml_responses_and_strips_source(self) -> None:
        class Response:
            text = "<ENVELOPE><BODY><DATA><STATUS>1</STATUS></DATA></BODY></ENVELOPE>"

            def raise_for_status(self):
                return None

        sent = {}

        def fake_post(url, **kwargs):
            sent.update(kwargs)
            return Response()

        with patch("requests.post", side_effect=fake_post):
            result = TallyClient().create_sales_voucher(
                {
                    "VoucherTypeName": "Sales",
                    "Date": "2026-05-04",
                    "PartyLedgerName": "Cash",
                    "Source": {"source_fingerprint": "abc"},
                    "InventoryEntries": [{"StockItemName": "2.75-18 NGP", "Rate": 1600, "Amount": 1600, "Quantity": 1}],
                    "LedgerEntries": [
                        {"LedgerName": "Sales", "Amount": 1600},
                        {"LedgerName": "Cash", "Amount": -1600},
                    ],
                }
            )

        self.assertIn("data", sent)
        self.assertNotIn("Source", sent["data"])
        self.assertIn("ENVELOPE", result)

    def test_tally_client_surfaces_xml_line_errors(self) -> None:
        class Response:
            text = "<ENVELOPE><BODY><DATA><LINEERROR>Bad voucher</LINEERROR></DATA></BODY></ENVELOPE>"

            def raise_for_status(self):
                return None

        with patch("requests.post", return_value=Response()):
            with self.assertRaisesRegex(TallyError, "Bad voucher"):
                TallyClient().export_data("Ledgers")

    def test_tally_client_wraps_network_errors(self) -> None:
        with patch("requests.post", side_effect=requests.ConnectionError("connection refused")):
            with self.assertRaisesRegex(TallyError, "connection refused"):
                TallyClient().export_data("Ledgers")


if __name__ == "__main__":
    unittest.main()
