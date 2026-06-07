from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
from typing import Any

from backend import config
from backend.db import database


IMPORT_TYPE_RETAIL = "retail_sales"
IMPORT_TYPE_GST = "gst_tax_invoice"


class GstInvoiceError(ValueError):
    pass


@dataclass
class GstBuildResult:
    vouchers: list[dict[str, Any]]
    errors: list[dict[str, Any]]


def normalize_import_type(value: str | None) -> str:
    normalized = str(value or IMPORT_TYPE_RETAIL).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "retail": IMPORT_TYPE_RETAIL,
        "retail_sale": IMPORT_TYPE_RETAIL,
        "sales": IMPORT_TYPE_RETAIL,
        "gst": IMPORT_TYPE_GST,
        "gst_sales": IMPORT_TYPE_GST,
        "gst_invoice": IMPORT_TYPE_GST,
        "gst_sales_invoice": IMPORT_TYPE_GST,
        "gst_tax_invoices": IMPORT_TYPE_GST,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {IMPORT_TYPE_RETAIL, IMPORT_TYPE_GST}:
        raise GstInvoiceError("Unsupported upload type")
    return normalized


def import_type_label(import_type: str | None) -> str:
    return "Invoice for GST Firms" if normalize_import_type(import_type) == IMPORT_TYPE_GST else "Invoice for Individual Customers"


def validate_gstin(value: str) -> bool:
    return bool(re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value.strip().upper()))


def build_gst_invoices(rows: list[dict[str, Any]], company: dict[str, Any], user_id: int | None = None) -> GstBuildResult:
    vouchers: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        try:
            vouchers.append(build_gst_invoice(row, company, index=index, user_id=user_id))
        except Exception as exc:
            errors.append({"row": index, "product_name": row.get("product_name", ""), "error": str(exc)})
    return GstBuildResult(vouchers=vouchers, errors=errors)


def build_gst_invoice(row: dict[str, Any], company: dict[str, Any], index: int = 0, user_id: int | None = None) -> dict[str, Any]:
    _require_company_gst_config(company)
    voucher_date = _parse_voucher_date(row.get("voucher_date"))
    product_name = str(row.get("product_name", "")).strip()
    buyer_name = str(row.get("buyer_name", "")).strip()
    buyer_gstin = str(row.get("buyer_gstin", "")).strip().upper()
    buyer_state = str(row.get("buyer_state", "")).strip()
    payment_mode = str(row.get("payment_mode", "")).strip().lower()
    quantity = _positive_float(row.get("quantity"), "quantity")
    rate = _positive_float(row.get("rate") if row.get("rate") is not None else row.get("price"), "rate")

    if not buyer_name:
        raise GstInvoiceError("buyer_name is required for GST invoices")
    if not validate_gstin(buyer_gstin):
        raise GstInvoiceError("buyer_gstin must be a valid GSTIN")
    if not buyer_state:
        raise GstInvoiceError("buyer_state is required for GST invoices")
    if not product_name:
        raise GstInvoiceError("product_name is required")

    stock_item = database.get_stock_item_by_name(product_name, company_id=company["id"])
    if not stock_item:
        if database.stock_item_sync_has_failures(company["id"]):
            raise GstInvoiceError("Product not found in synced Tally stock items. Some stock groups need retry, so retry failed groups if this product exists in Tally.")
        raise GstInvoiceError("Product not found in synced Tally stock items")
    stock = dict(stock_item)
    gst_rate = _positive_or_zero(stock.get("gst_rate"), "GST rate")
    if gst_rate <= 0:
        raise GstInvoiceError("GST rate is missing for this stock item")
    hsn_code = str(stock.get("hsn_code") or "").strip()

    tax = calculate_gst_totals(
        taxable_amount=quantity * rate,
        gst_rate=gst_rate,
        company_state=str(company.get("supplier_state") or ""),
        buyer_state=buyer_state,
    )
    source = _build_source(row, index, voucher_date, company_id=company["id"], user_id=user_id)
    source["import_type"] = IMPORT_TYPE_GST

    return {
        "VoucherKind": IMPORT_TYPE_GST,
        "VoucherTypeName": "Sales",
        "Date": voucher_date.isoformat(),
        "PartyLedgerName": buyer_name,
        "BuyerName": buyer_name,
        "BuyerGSTIN": buyer_gstin,
        "BuyerState": buyer_state,
        "BuyerAddress": str(row.get("buyer_address") or "").strip(),
        "PlaceOfSupply": str(row.get("place_of_supply") or buyer_state).strip(),
        "PaymentMode": payment_mode,
        "CompanyGSTIN": str(company.get("supplier_gstin") or "").strip().upper(),
        "CompanyState": str(company.get("supplier_state") or "").strip(),
        "GSTRegistrationName": str(company.get("gst_registration_name") or config.GST_REGISTRATION_NAME),
        "GSTRegistrationType": str(company.get("gst_registration_type") or config.GST_REGISTRATION_TYPE),
        "SalesLedgerName": str(company.get("gst_sales_ledger_name") or config.GST_SALES_LEDGER_NAME),
        "CGSTLedgerName": str(company.get("cgst_ledger_name") or config.CGST_LEDGER_NAME),
        "SGSTLedgerName": str(company.get("sgst_ledger_name") or config.SGST_LEDGER_NAME),
        "IGSTLedgerName": str(company.get("igst_ledger_name") or config.IGST_LEDGER_NAME),
        "TaxableAmount": tax["taxable_amount"],
        "GSTAmount": tax["gst_amount"],
        "InvoiceTotal": tax["invoice_total"],
        "TaxSplit": tax,
        "Source": source,
        "InventoryEntries": [
            {
                "StockItemName": stock["name"],
                "Rate": rate,
                "Amount": tax["taxable_amount"],
                "Quantity": quantity,
                "Unit": stock.get("base_unit") or "nos",
                "HSNCode": hsn_code,
                "GSTType": stock.get("gst_type") or "Goods",
                "Taxability": stock.get("taxability") or "Taxable",
                "GSTRate": gst_rate,
                "CGSTRate": tax["cgst_rate"],
                "SGSTRate": tax["sgst_rate"],
                "IGSTRate": tax["igst_rate"],
                "SalesLedgerName": str(company.get("gst_sales_ledger_name") or config.GST_SALES_LEDGER_NAME),
            }
        ],
    }


def calculate_gst_totals(taxable_amount: float, gst_rate: float, company_state: str, buyer_state: str) -> dict[str, float | bool]:
    taxable_amount = round(float(taxable_amount), 2)
    gst_rate = float(gst_rate)
    same_state = _normalize_state(company_state) == _normalize_state(buyer_state)
    gst_amount = round(taxable_amount * gst_rate / 100, 2)
    if same_state:
        cgst_amount = round(gst_amount / 2, 2)
        sgst_amount = round(gst_amount - cgst_amount, 2)
        igst_amount = 0.0
    else:
        cgst_amount = 0.0
        sgst_amount = 0.0
        igst_amount = gst_amount
    return {
        "taxable_amount": taxable_amount,
        "gst_rate": gst_rate,
        "same_state": same_state,
        "cgst_rate": gst_rate / 2 if same_state else 0.0,
        "sgst_rate": gst_rate / 2 if same_state else 0.0,
        "igst_rate": 0.0 if same_state else gst_rate,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": igst_amount,
        "gst_amount": round(cgst_amount + sgst_amount + igst_amount, 2),
        "invoice_total": round(taxable_amount + cgst_amount + sgst_amount + igst_amount, 2),
    }


def required_gst_ledgers_for_rows(rows: list[dict[str, Any]], company: dict[str, Any]) -> list[dict[str, str]]:
    ledgers = [
        {"ledger_name": str(company.get("gst_sales_ledger_name") or config.GST_SALES_LEDGER_NAME), "group_name": config.GST_SALES_LEDGER_GROUP},
    ]
    for row in rows:
        buyer_name = str(row.get("buyer_name") or "").strip()
        if buyer_name:
            ledgers.append({"ledger_name": buyer_name, "group_name": str(company.get("gst_buyer_ledger_group") or config.GST_BUYER_LEDGER_GROUP)})
        same_state = _normalize_state(company.get("supplier_state")) == _normalize_state(row.get("buyer_state"))
        if same_state:
            ledgers.extend(
                [
                    {"ledger_name": str(company.get("cgst_ledger_name") or config.CGST_LEDGER_NAME), "group_name": "Duties & Taxes"},
                    {"ledger_name": str(company.get("sgst_ledger_name") or config.SGST_LEDGER_NAME), "group_name": "Duties & Taxes"},
                ]
            )
        else:
            ledgers.append({"ledger_name": str(company.get("igst_ledger_name") or config.IGST_LEDGER_NAME), "group_name": "Duties & Taxes"})

    deduped: dict[str, dict[str, str]] = {}
    for ledger in ledgers:
        name = ledger["ledger_name"].strip()
        if name:
            deduped.setdefault(name.lower(), {"ledger_name": name, "group_name": ledger["group_name"]})
    return list(deduped.values())


def _require_company_gst_config(company: dict[str, Any]) -> None:
    missing = []
    for key, label in [("supplier_gstin", "supplier GSTIN"), ("supplier_state", "supplier state")]:
        if not str(company.get(key) or "").strip():
            missing.append(label)
    if missing:
        raise GstInvoiceError(f"GST company configuration is missing: {', '.join(missing)}")
    if not validate_gstin(str(company.get("supplier_gstin") or "")):
        raise GstInvoiceError("supplier_gstin must be a valid GSTIN")


def _parse_voucher_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise GstInvoiceError("voucher_date is required")
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise GstInvoiceError("voucher_date must be YYYY-MM-DD") from exc


def _positive_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise GstInvoiceError(f"{label} must be a positive number") from exc
    if parsed <= 0:
        raise GstInvoiceError(f"{label} must be a positive number")
    return parsed


def _positive_or_zero(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise GstInvoiceError(f"{label} is missing") from exc
    return parsed


def _normalize_state(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _build_source(row: dict[str, Any], index: int, voucher_date: date, company_id: int, user_id: int | None = None) -> dict[str, Any]:
    source_row_id = str(row.get("source_row_id") or index + 1)
    raw_import_id = row.get("import_id") or voucher_date.isoformat()
    fingerprint_payload = {
        "import_type": IMPORT_TYPE_GST,
        "import_id": str(raw_import_id),
        "company_id": company_id,
        "source_row_id": source_row_id,
        "product_name": str(row.get("product_name", "")).strip().lower(),
        "buyer_gstin": str(row.get("buyer_gstin", "")).strip().upper(),
        "quantity": round(float(row.get("quantity") or 0), 4),
        "rate": round(float(row.get("rate") if row.get("rate") is not None else row.get("price") or 0), 2),
        "voucher_date": voucher_date.isoformat(),
    }
    return {
        "user_id": user_id,
        "company_id": company_id,
        "import_id": raw_import_id,
        "import_row_id": row.get("import_row_id"),
        "source_row_id": source_row_id,
        "source_fingerprint": hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest(),
    }
