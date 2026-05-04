from __future__ import annotations

import os


TALLY_URL = os.getenv("TALLY_URL", "http://localhost:9000")
TALLY_TRANSPORT = os.getenv("TALLY_TRANSPORT", "xml").lower()
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
SALES_LEDGER_NAME = os.getenv("SALES_LEDGER_NAME", "Sales")
CASH_LEDGER_NAME = os.getenv("CASH_LEDGER_NAME", "Cash")
MASTER_CACHE_MAX_AGE_HOURS = int(os.getenv("MASTER_CACHE_MAX_AGE_HOURS", "24"))
UPI_FALLBACK_LEDGER = os.getenv("UPI_FALLBACK_LEDGER", "UPI Sales")
UPI_FALLBACK_GROUP = os.getenv("UPI_FALLBACK_GROUP", "Sundry Debtors")
