from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {"product_name", "price", "payment_mode", "voucher_date"}
VALID_PAYMENT_MODES = {"cash", "upi"}


class ExcelParseError(ValueError):
    pass


def parse_excel(content: bytes) -> list[dict[str, Any]]:
    try:
        dataframe = pd.read_excel(BytesIO(content))
    except Exception as exc:  # pandas raises several parser-specific exceptions.
        raise ExcelParseError("Unable to read Excel file") from exc

    dataframe.columns = [_normalize_column(column) for column in dataframe.columns]
    missing = REQUIRED_COLUMNS - set(dataframe.columns)
    if missing:
        raise ExcelParseError(f"Missing required columns: {', '.join(sorted(missing))}")

    rows: list[dict[str, Any]] = []
    for index, row in dataframe.iterrows():
        if row[list(REQUIRED_COLUMNS)].isna().all():
            continue

        product_name = str(row["product_name"]).strip()
        payment_mode = str(row["payment_mode"]).strip().lower()
        price = pd.to_numeric(row["price"], errors="coerce")
        voucher_date = _parse_date(row["voucher_date"])

        if not product_name or product_name.lower() == "nan":
            raise ExcelParseError(f"Row {index + 2}: product_name is required")
        if pd.isna(price) or float(price) <= 0:
            raise ExcelParseError(f"Row {index + 2}: price must be a positive number")
        if payment_mode not in VALID_PAYMENT_MODES:
            raise ExcelParseError(
                f"Row {index + 2}: payment_mode must be one of {', '.join(sorted(VALID_PAYMENT_MODES))}"
            )
        if voucher_date is None:
            raise ExcelParseError(f"Row {index + 2}: voucher_date is required")

        rows.append(
            {
                "product_name": product_name,
                "price": float(price),
                "payment_mode": payment_mode,
                "voucher_date": voucher_date.isoformat(),
                "source_row_id": str(index + 2),
            }
        )

    if not rows:
        raise ExcelParseError("Excel file contains no valid rows")
    return rows


def _normalize_column(column: Any) -> str:
    return str(column).strip().lower().replace(" ", "_")


def _parse_date(value: Any) -> date | None:
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()
