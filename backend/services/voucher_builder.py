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

        try:
            items = _row_items(row)
            product_name = ", ".join(item.get("product_name", "") for item in items)
            voucher_date = _parse_voucher_date(row.get("voucher_date"))
            party_ledger = _resolve_party_ledger(str(row.get("payment_mode", "")).lower(), ensure_ledgers, company=company)
            source = _build_source(row, index, voucher_date, company_id=company_id, user_id=user_id)
            voucher_items = []
            for item in items:
                item_name = str(item.get("product_name", "")).strip()
                stock_item = database.get_stock_item_by_name(item_name, company_id=company_id)
                if not stock_item:
                    raise VoucherBuildError(_missing_stock_item_error(company_id))
                voucher_items.append(
                    {
                        "stock_item_name": dict(stock_item)["name"],
                        "price": float(item["price"]),
                        "quantity": _positive_float(item.get("quantity") or 1, "quantity"),
                        "stock_item": dict(stock_item),
                    }
                )
            voucher = _build_sales_voucher(
                items=voucher_items,
                payment_mode=str(row["payment_mode"]).lower(),
                voucher_date=voucher_date.isoformat(),
                party_ledger=party_ledger,
                sales_ledger=sales_ledger,
                source=source,
                company=company,
            )
            _validate_voucher(voucher)
            vouchers.append(voucher)
        except Exception as exc:
            errors.append({"row": index, "product_name": product_name, "error": str(exc)})

    return BuildResult(vouchers=vouchers, errors=errors)


def _resolve_sales_ledger(company: dict[str, Any] | None = None) -> str | None:
    company_id = company["id"] if company else None
    sales_ledger_name = _company_value(company, "sales_ledger_name", config.SALES_LEDGER_NAME)
    ledger = database.get_ledger_by_name(sales_ledger_name, company_id=company_id)
    if company:
        return ledger["name"] if ledger else sales_ledger_name
    return ledger["name"] if ledger else None


def _sales_ledger_error(company: dict[str, Any] | None = None) -> str:
    sales_ledger_name = _company_value(company, "sales_ledger_name", config.SALES_LEDGER_NAME)
    return f'Required sales ledger "{sales_ledger_name}" not found in cache'


def _missing_stock_item_error(company_id: int) -> str:
    if database.stock_item_sync_has_failures(company_id):
        return "Product not found in synced Tally stock items. Some stock groups need retry, so retry failed groups if this product exists in Tally."
    return "Product not found in synced Tally stock items"


def _resolve_party_ledger(payment_mode: str, ensure_ledgers: bool, company: dict[str, Any] | None = None) -> str:
    company_id = company["id"] if company else None
    ledger = resolve_payment_ledger(payment_mode, company)
    if ensure_ledgers:
        _ensure_ledger_exists(ledger["ledger_name"], ledger["group_name"], company=company)
    if not database.get_ledger_by_name(ledger["ledger_name"], company_id=company_id):
        if company:
            return ledger["ledger_name"]
        raise VoucherBuildError(f'Required payment ledger "{ledger["ledger_name"]}" not found in cache')
    return ledger["ledger_name"]


def resolve_payment_ledger(payment_mode: str, company: dict[str, Any] | None = None) -> dict[str, str]:
    normalized = str(payment_mode).strip().lower()
    mappings = _payment_ledger_mappings(company)
    if normalized in mappings:
        return mappings[normalized]
    fallback_name = _payment_mode_to_ledger_name(normalized)
    return {
        "ledger_name": fallback_name,
        "group_name": _company_value(company, "payment_default_group_name", config.DEFAULT_PAYMENT_LEDGER_GROUP),
    }


def required_ledgers_for_rows(rows: list[dict[str, Any]], company: dict[str, Any]) -> list[dict[str, str]]:
    required = [
        {
            "ledger_name": _company_value(company, "sales_ledger_name", config.SALES_LEDGER_NAME),
            "group_name": _company_value(company, "sales_ledger_group_name", config.SALES_LEDGER_GROUP),
        }
    ]
    for row in rows:
        required.append(resolve_payment_ledger(str(row.get("payment_mode", "")), company))
    required.extend(
        [
            {"ledger_name": _company_value(company, "cgst_ledger_name", config.CGST_LEDGER_NAME), "group_name": "Duties & Taxes"},
            {"ledger_name": _company_value(company, "sgst_ledger_name", config.SGST_LEDGER_NAME), "group_name": "Duties & Taxes"},
        ]
    )

    deduped: dict[str, dict[str, str]] = {}
    for ledger in required:
        name = ledger["ledger_name"].strip()
        if name:
            deduped.setdefault(name.lower(), {"ledger_name": name, "group_name": ledger["group_name"]})
    return list(deduped.values())


def _payment_ledger_mappings(company: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    mappings: dict[str, dict[str, str]] = {
        "cash": {
            "ledger_name": _company_value(company, "cash_ledger_name", config.CASH_LEDGER_NAME),
            "group_name": _company_value(company, "cash_ledger_group_name", config.CASH_LEDGER_GROUP),
        },
        "upi": {
            "ledger_name": _company_value(company, "upi_fallback_ledger_name", config.UPI_FALLBACK_LEDGER),
            "group_name": _company_value(company, "upi_fallback_group_name", config.UPI_FALLBACK_GROUP),
        },
    }
    raw = company.get("payment_ledger_mappings") if company else None
    if raw:
        try:
            custom = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            custom = {}
        if isinstance(custom, dict):
            for mode, item in custom.items():
                if not isinstance(item, dict):
                    continue
                ledger_name = str(item.get("ledger_name", "")).strip()
                group_name = str(item.get("group_name") or _company_value(company, "payment_default_group_name", config.DEFAULT_PAYMENT_LEDGER_GROUP)).strip()
                if ledger_name:
                    mappings[str(mode).strip().lower()] = {"ledger_name": ledger_name, "group_name": group_name}
    return mappings


def _payment_mode_to_ledger_name(payment_mode: str) -> str:
    return " ".join(part.capitalize() for part in payment_mode.replace("_", " ").replace("-", " ").split())


def _row_items(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = row.get("items")
    if raw_items:
        if not isinstance(raw_items, list):
            raise VoucherBuildError("items must be a list")
        items = raw_items
    else:
        items = [
            {
                "product_name": row.get("product_name"),
                "price": row.get("price"),
                "quantity": row.get("quantity") or 1,
            }
        ]
    if not items:
        raise VoucherBuildError("At least one item is required")
    normalized = []
    for index, item in enumerate(items):
        product_name = str((item or {}).get("product_name", "")).strip()
        if not product_name:
            raise VoucherBuildError(f"items[{index}].product_name is required")
        normalized.append(
            {
                "product_name": product_name,
                "price": _positive_float((item or {}).get("price"), "price"),
                "quantity": _positive_float((item or {}).get("quantity") or 1, "quantity"),
            }
        )
    return normalized


def _company_value(company: dict[str, Any] | None, key: str, default: str) -> str:
    if not company:
        return default
    value = company.get(key)
    return str(value).strip() if value else default


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
    items: list[dict[str, Any]],
    payment_mode: str,
    voucher_date: str,
    party_ledger: str,
    sales_ledger: str,
    source: dict[str, Any],
    company: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inventory_entries = []
    taxable_amount = 0.0
    cgst_amount = 0.0
    sgst_amount = 0.0
    invoice_total = 0.0
    gst_rate = 0.0
    for item in items:
        stock_item = item["stock_item"]
        quantity = item["quantity"]
        tax = _calculate_inclusive_cgst_sgst(item["price"], stock_item)
        line_sales_amount = float(tax["taxable_amount"])
        unit_rate = round(line_sales_amount / quantity, 2)
        taxable_amount = round(taxable_amount + line_sales_amount, 2)
        cgst_amount = round(cgst_amount + float(tax["cgst_amount"]), 2)
        sgst_amount = round(sgst_amount + float(tax["sgst_amount"]), 2)
        invoice_total = round(invoice_total + float(tax["invoice_total"]), 2)
        gst_rate = float(tax["gst_rate"]) if not gst_rate else gst_rate
        inventory_entries.append(
            {
                "StockItemName": item["stock_item_name"],
                "Rate": unit_rate,
                "Amount": line_sales_amount,
                "Quantity": quantity,
                "Unit": stock_item.get("base_unit") or "nos",
                "HSNCode": stock_item.get("hsn_code") or "",
                "GSTType": stock_item.get("gst_type") or "Goods",
                "Taxability": stock_item.get("taxability") or "Taxable",
                "GSTRate": tax["gst_rate"],
                "CGSTRate": tax["cgst_rate"],
                "SGSTRate": tax["sgst_rate"],
                "IGSTRate": tax["igst_rate"],
                "SalesLedgerName": sales_ledger,
            }
        )
    gst_amount = round(cgst_amount + sgst_amount, 2)
    tax = {
        "taxable_amount": taxable_amount,
        "gst_rate": gst_rate,
        "same_state": True,
        "cgst_rate": gst_rate / 2 if gst_rate else 0.0,
        "sgst_rate": gst_rate / 2 if gst_rate else 0.0,
        "igst_rate": 0.0,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": 0.0,
        "gst_amount": gst_amount,
        "invoice_total": invoice_total,
    }
    cgst_ledger = _company_value(company, "cgst_ledger_name", config.CGST_LEDGER_NAME)
    sgst_ledger = _company_value(company, "sgst_ledger_name", config.SGST_LEDGER_NAME)
    return {
        "VoucherKind": "individual_customer_invoice",
        "VoucherTypeName": "Sales",
        "Date": voucher_date,
        "PartyLedgerName": party_ledger,
        "PaymentMode": payment_mode,
        "CGSTLedgerName": cgst_ledger,
        "SGSTLedgerName": sgst_ledger,
        "TaxableAmount": taxable_amount,
        "GSTAmount": gst_amount,
        "InvoiceTotal": invoice_total,
        "TaxSplit": tax,
        "Source": source,
        "InventoryEntries": inventory_entries,
        "LedgerEntries": [
            {
                "LedgerName": sales_ledger,
                "Amount": taxable_amount,
            },
            {
                "LedgerName": cgst_ledger,
                "Amount": tax["cgst_amount"],
            },
            {
                "LedgerName": sgst_ledger,
                "Amount": tax["sgst_amount"],
            },
            {
                "LedgerName": party_ledger,
                "Amount": -invoice_total,
            },
        ],
    }


def _calculate_inclusive_cgst_sgst(price: float, stock_item: dict[str, Any]) -> dict[str, float | bool]:
    invoice_total = round(float(price), 2)
    if invoice_total <= 0:
        raise VoucherBuildError("price must be a positive number")
    gst_rate = _positive_or_zero(stock_item.get("gst_rate"), "GST rate")
    if gst_rate <= 0:
        raise VoucherBuildError("GST rate is missing for this stock item")
    taxable_amount = round(invoice_total * 100 / (100 + gst_rate), 2)
    gst_amount = round(invoice_total - taxable_amount, 2)
    cgst_amount = round(gst_amount / 2, 2)
    sgst_amount = round(gst_amount - cgst_amount, 2)
    return {
        "taxable_amount": taxable_amount,
        "gst_rate": gst_rate,
        "same_state": True,
        "cgst_rate": gst_rate / 2,
        "sgst_rate": gst_rate / 2,
        "igst_rate": 0.0,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": 0.0,
        "gst_amount": round(cgst_amount + sgst_amount, 2),
        "invoice_total": invoice_total,
    }


def _positive_or_zero(value: Any, label: str) -> float:
    if value in {None, ""}:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise VoucherBuildError(f"{label} must be a number") from exc
    if parsed < 0:
        raise VoucherBuildError(f"{label} must be zero or greater")
    return parsed


def _positive_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise VoucherBuildError(f"{label} must be a positive number") from exc
    if parsed <= 0:
        raise VoucherBuildError(f"{label} must be a positive number")
    return parsed


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
    items = _row_items(row)
    fingerprint_payload = {
        "import_id": import_id_for_fingerprint,
        "company_id": company_id,
        "source_row_id": source_row_id,
        "items": [
            {
                "product_name": item["product_name"].lower(),
                "price": round(float(item["price"]), 2),
                "quantity": round(float(item["quantity"]), 4),
            }
            for item in items
        ],
        "payment_mode": str(row.get("payment_mode", "")).strip().lower(),
        "voucher_date": voucher_date.isoformat(),
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "user_id": user_id,
        "company_id": company_id,
        "import_id": raw_import_id,
        "import_row_id": row.get("import_row_id"),
        "import_row_ids": row.get("import_row_ids") or ([row.get("import_row_id")] if row.get("import_row_id") else []),
        "source_row_id": source_row_id,
        "source_fingerprint": fingerprint,
    }
