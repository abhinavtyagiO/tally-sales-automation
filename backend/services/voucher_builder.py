from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Any

from backend import config
from backend.db import database
from backend.services.sync_service import has_company_master_cache, has_master_cache
from backend.services.tally_client import TallyClient


CASH_LEDGER = "Cash"


class VoucherBuildError(ValueError):
    pass


@dataclass
class BuildResult:
    vouchers: list[dict[str, Any]]
    errors: list[dict[str, Any]]


def build_vouchers(
    rows: list[dict[str, Any]],
    ensure_ledgers: bool = False,
    company: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> BuildResult:
    vouchers: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if company and not has_company_master_cache(company):
        raise VoucherBuildError("Tally master cache is missing or stale for this company. Run company sync first.")
    if not company and not has_master_cache():
        raise VoucherBuildError("Tally master cache is missing or stale. Run /sync first.")
    company_id = company["id"] if company else database.ensure_legacy_company()["id"]

    for index, row in enumerate(rows):
        product_name = str(row.get("product_name", "")).strip()
        sales_ledger = _resolve_sales_ledger(company=company)
        if not sales_ledger:
            errors.append({"row": index, "product_name": product_name, "error": _sales_ledger_error(company)})
            continue

        stock_item = database.get_stock_item_by_name(product_name, company_id=company_id)
        if not stock_item:
            errors.append(
                {
                    "row": index,
                    "product_name": product_name,
                    "error": "Product not found in synced Tally stock items",
                }
            )
            continue

        try:
            voucher_date = _parse_voucher_date(row.get("voucher_date"))
            party_ledger = _resolve_party_ledger(str(row.get("payment_mode", "")).lower(), ensure_ledgers, company=company)
            source = _build_source(row, index, voucher_date, company_id=company_id, user_id=user_id)
            if ensure_ledgers and database.successful_fingerprint_exists(source["source_fingerprint"], company_id=company_id):
                raise VoucherBuildError("Duplicate source row was already committed successfully")
            voucher = _build_sales_voucher(
                stock_item_name=stock_item["name"],
                price=float(row["price"]),
                payment_mode=str(row["payment_mode"]).lower(),
                voucher_date=voucher_date.isoformat(),
                party_ledger=party_ledger,
                sales_ledger=sales_ledger,
                source=source,
            )
            _validate_voucher(voucher)
            vouchers.append(voucher)
        except Exception as exc:
            errors.append({"row": index, "product_name": product_name, "error": str(exc)})

    return BuildResult(vouchers=vouchers, errors=errors)


def _resolve_sales_ledger(company: dict[str, Any] | None = None) -> str | None:
    company_id = company["id"] if company else None
    sales_ledger_name = company.get("sales_ledger_name") if company else config.SALES_LEDGER_NAME
    ledger = database.get_ledger_by_name(sales_ledger_name, company_id=company_id)
    return ledger["name"] if ledger else None


def _sales_ledger_error(company: dict[str, Any] | None = None) -> str:
    sales_ledger_name = company.get("sales_ledger_name") if company else config.SALES_LEDGER_NAME
    return f'Required sales ledger "{sales_ledger_name}" not found in cache'


def _resolve_party_ledger(payment_mode: str, ensure_ledgers: bool, company: dict[str, Any] | None = None) -> str:
    company_id = company["id"] if company else None
    cash_ledger = company.get("cash_ledger_name") if company else config.CASH_LEDGER_NAME
    upi_ledger = company.get("upi_fallback_ledger_name") if company else config.UPI_FALLBACK_LEDGER
    upi_group = company.get("upi_fallback_group_name") if company else config.UPI_FALLBACK_GROUP
    if payment_mode == "cash":
        if not database.get_ledger_by_name(cash_ledger, company_id=company_id):
            raise VoucherBuildError(f'Required cash ledger "{cash_ledger}" not found in cache')
        return cash_ledger
    if payment_mode == "upi":
        if ensure_ledgers:
            _ensure_ledger_exists(upi_ledger, upi_group, company=company)
        if not database.get_ledger_by_name(upi_ledger, company_id=company_id):
            raise VoucherBuildError(f'Required fallback ledger "{upi_ledger}" not found in cache')
        return upi_ledger
    raise VoucherBuildError(f"Unsupported payment mode: {payment_mode}")


def _ensure_ledger_exists(name: str, group_name: str, company: dict[str, Any] | None = None) -> None:
    company_id = company["id"] if company else None
    if database.get_ledger_by_name(name, company_id=company_id):
        return
    if company:
        response = TallyClient().create_ledger(name, group_name, company_name=company.get("company_name"))
    else:
        response = TallyClient().create_ledger(name, group_name)
    database.upsert_ledger(name, group_name, company_id=company_id)
    database.log_voucher(
        {"operation": "create_ledger", "name": name, "group": group_name},
        response,
        "success",
    )


def _build_sales_voucher(
    stock_item_name: str,
    price: float,
    payment_mode: str,
    voucher_date: str,
    party_ledger: str,
    sales_ledger: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    amount = round(price, 2)
    return {
        "VoucherTypeName": "Sales",
        "Date": voucher_date,
        "PartyLedgerName": party_ledger,
        "PaymentMode": payment_mode,
        "Source": source,
        "InventoryEntries": [
            {
                "StockItemName": stock_item_name,
                "Rate": amount,
                "Amount": amount,
                "Quantity": 1,
            }
        ],
        "LedgerEntries": [
            {
                "LedgerName": sales_ledger,
                "Amount": amount,
            },
            {
                "LedgerName": party_ledger,
                "Amount": -amount,
            },
        ],
    }


def _validate_voucher(voucher: dict[str, Any]) -> None:
    if voucher.get("VoucherTypeName") != "Sales":
        raise VoucherBuildError("VoucherTypeName must be Sales")
    _parse_voucher_date(voucher.get("Date"))
    if not voucher.get("PartyLedgerName"):
        raise VoucherBuildError("PartyLedgerName is required")
    if not voucher.get("InventoryEntries"):
        raise VoucherBuildError("InventoryEntries are required")
    ledger_entries = voucher.get("LedgerEntries") or []
    total = round(sum(float(entry.get("Amount", 0)) for entry in ledger_entries), 2)
    if total != 0:
        raise VoucherBuildError(f"Voucher is not balanced; ledger total is {total}")


def validate_voucher(voucher: dict[str, Any]) -> None:
    _validate_voucher(voucher)


def _parse_voucher_date(value: Any) -> date:
    if not value:
        raise VoucherBuildError("voucher_date is required")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise VoucherBuildError("voucher_date must be YYYY-MM-DD") from exc


def _build_source(row: dict[str, Any], index: int, voucher_date: date, company_id: int, user_id: int | None = None) -> dict[str, Any]:
    source_row_id = str(row.get("source_row_id") or index + 1)
    raw_import_id = row.get("import_id") or voucher_date.isoformat()
    import_id_for_fingerprint = str(raw_import_id)
    fingerprint_payload = {
        "import_id": import_id_for_fingerprint,
        "company_id": company_id,
        "source_row_id": source_row_id,
        "product_name": str(row.get("product_name", "")).strip().lower(),
        "price": round(float(row.get("price", 0)), 2),
        "payment_mode": str(row.get("payment_mode", "")).strip().lower(),
        "voucher_date": voucher_date.isoformat(),
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "user_id": user_id,
        "company_id": company_id,
        "import_id": raw_import_id,
        "import_row_id": row.get("import_row_id"),
        "source_row_id": source_row_id,
        "source_fingerprint": fingerprint,
    }
