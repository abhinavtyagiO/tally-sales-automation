from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd

from backend.services.gst_invoice import IMPORT_TYPE_GST, IMPORT_TYPE_RETAIL, normalize_import_type, validate_gstin


RETAIL_REQUIRED_COLUMNS = {"product_name", "price", "payment_mode", "voucher_date"}
GST_REQUIRED_COLUMNS = {"voucher_date", "buyer_name", "buyer_gstin", "buyer_state", "product_name", "quantity", "rate", "payment_mode"}


class ExcelParseError(ValueError):
    pass


def parse_excel(content: bytes, import_type: str = IMPORT_TYPE_RETAIL) -> list[dict[str, Any]]:
    import_type = normalize_import_type(import_type)
    try:
        dataframe = pd.read_excel(BytesIO(content))
    except Exception as exc:  # pandas raises several parser-specific exceptions.
        raise ExcelParseError("Unable to read Excel file") from exc

    dataframe.columns = [_normalize_column(column) for column in dataframe.columns]
    required_columns = GST_REQUIRED_COLUMNS if import_type == IMPORT_TYPE_GST else RETAIL_REQUIRED_COLUMNS
    missing = required_columns - set(dataframe.columns)
    if missing:
        raise ExcelParseError(f"Missing required columns: {', '.join(sorted(missing))}")

    rows: list[dict[str, Any]] = []
    for index, row in dataframe.iterrows():
        if row[list(required_columns)].isna().all():
            continue
        if import_type == IMPORT_TYPE_GST:
            rows.append(_parse_gst_row(row, index))
            continue

        product_name = str(row["product_name"]).strip()
        payment_mode = str(row["payment_mode"]).strip().lower()
        price = pd.to_numeric(row["price"], errors="coerce")
        quantity = pd.to_numeric(row["quantity"], errors="coerce") if "quantity" in row else 1
        voucher_date = _parse_date(row["voucher_date"])
        voucher_id = _cell_text(row.get("voucher_id")) if "voucher_id" in row else ""

        if not product_name or product_name.lower() == "nan":
            raise ExcelParseError(f"Row {index + 2}: product_name is required")
        if pd.isna(price) or float(price) <= 0:
            raise ExcelParseError(f"Row {index + 2}: price must be a positive number")
        if pd.isna(quantity) or float(quantity) <= 0:
            raise ExcelParseError(f"Row {index + 2}: quantity must be a positive number")
        if not payment_mode or payment_mode == "nan":
            raise ExcelParseError(f"Row {index + 2}: payment_mode is required")
        if voucher_date is None:
            raise ExcelParseError(f"Row {index + 2}: voucher_date is required")

        rows.append(
            {
                "product_name": product_name,
                "price": float(price),
                "quantity": float(quantity),
                "payment_mode": payment_mode,
                "voucher_date": voucher_date.isoformat(),
                "voucher_id": voucher_id or None,
                "source_row_id": str(index + 2),
            }
        )

    if not rows:
        raise ExcelParseError("Excel file contains no valid rows")
    return rows


def _parse_gst_row(row: Any, index: int) -> dict[str, Any]:
    product_name = _cell_text(row["product_name"])
    payment_mode = _cell_text(row["payment_mode"]).lower()
    buyer_name = _cell_text(row["buyer_name"])
    buyer_gstin = _cell_text(row["buyer_gstin"]).upper()
    buyer_state = _cell_text(row["buyer_state"])
    buyer_address = _cell_text(row.get("buyer_address")) if "buyer_address" in row else ""
    place_of_supply = _cell_text(row.get("place_of_supply")) if "place_of_supply" in row else buyer_state
    voucher_id = _cell_text(row.get("voucher_id")) if "voucher_id" in row else ""
    quantity = pd.to_numeric(row["quantity"], errors="coerce")
    rate = pd.to_numeric(row["rate"], errors="coerce")
    voucher_date = _parse_date(row["voucher_date"])

    if not product_name:
        raise ExcelParseError(f"Row {index + 2}: product_name is required")
    if not buyer_name:
        raise ExcelParseError(f"Row {index + 2}: buyer_name is required")
    if not validate_gstin(buyer_gstin):
        raise ExcelParseError(f"Row {index + 2}: buyer_gstin must be a valid GSTIN")
    if not buyer_state:
        raise ExcelParseError(f"Row {index + 2}: buyer_state is required")
    if pd.isna(quantity) or float(quantity) <= 0:
        raise ExcelParseError(f"Row {index + 2}: quantity must be a positive number")
    if pd.isna(rate) or float(rate) <= 0:
        raise ExcelParseError(f"Row {index + 2}: rate must be a positive number")
    if not payment_mode:
        raise ExcelParseError(f"Row {index + 2}: payment_mode is required")
    if voucher_date is None:
        raise ExcelParseError(f"Row {index + 2}: voucher_date is required")

    return {
        "product_name": product_name,
        "price": float(rate),
        "quantity": float(quantity),
        "rate": float(rate),
        "payment_mode": payment_mode,
        "voucher_date": voucher_date.isoformat(),
        "buyer_name": buyer_name,
        "buyer_gstin": buyer_gstin,
        "buyer_state": buyer_state,
        "buyer_address": buyer_address,
        "place_of_supply": place_of_supply or buyer_state,
        "voucher_id": voucher_id or None,
        "source_row_id": str(index + 2),
    }


def _normalize_column(column: Any) -> str:
    return str(column).strip().lower().replace(" ", "_")


def _cell_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_date(value: Any) -> date | None:
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()
