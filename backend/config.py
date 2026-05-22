from __future__ import annotations

import os
from pathlib import Path


def _load_local_env() -> None:
    for env_path in (Path(__file__).resolve().parent.parent / ".env", Path(__file__).resolve().parent / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()

APP_ENV = os.getenv("APP_ENV", "development").lower()
DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "")

TALLY_URL = os.getenv("TALLY_URL", "http://127.0.0.1:9000")
TALLY_TRANSPORT = os.getenv("TALLY_TRANSPORT", "xml").lower()
LOCAL_AGENT_URL = os.getenv("LOCAL_AGENT_URL", "http://localhost:9100")
CONNECTOR_MODE = os.getenv("CONNECTOR_MODE", "direct").lower()
LOCAL_AGENT_BOOTSTRAP_ENABLED = os.getenv("LOCAL_AGENT_BOOTSTRAP_ENABLED", "true" if APP_ENV != "production" else "false").lower() == "true"
LOCAL_AGENT_TOKEN = os.getenv("LOCAL_AGENT_TOKEN", "")
LEGACY_ENDPOINTS_ENABLED = os.getenv("LEGACY_ENDPOINTS_ENABLED", "true" if APP_ENV != "production" else "false").lower() == "true"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
ALLOW_DEV_AUTH = os.getenv("ALLOW_DEV_AUTH", "false").lower() == "true"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]
SALES_LEDGER_NAME = os.getenv("SALES_LEDGER_NAME", "Sales")
SALES_LEDGER_GROUP = os.getenv("SALES_LEDGER_GROUP", "Sales Accounts")
CASH_LEDGER_NAME = os.getenv("CASH_LEDGER_NAME", "Cash")
CASH_LEDGER_GROUP = os.getenv("CASH_LEDGER_GROUP", "Cash-in-Hand")
MASTER_CACHE_MAX_AGE_HOURS = int(os.getenv("MASTER_CACHE_MAX_AGE_HOURS", "24"))
UPI_FALLBACK_LEDGER = os.getenv("UPI_FALLBACK_LEDGER", "UPI")
UPI_FALLBACK_GROUP = os.getenv("UPI_FALLBACK_GROUP", "Bank Accounts")
DEFAULT_PAYMENT_LEDGER_GROUP = os.getenv("DEFAULT_PAYMENT_LEDGER_GROUP", "Bank Accounts")
GST_REGISTRATION_TYPE = os.getenv("GST_REGISTRATION_TYPE", "Regular")
GST_REGISTRATION_NAME = os.getenv("GST_REGISTRATION_NAME", "GST Registration")
GST_SALES_LEDGER_NAME = os.getenv("GST_SALES_LEDGER_NAME", "GST Sales")
GST_SALES_LEDGER_GROUP = os.getenv("GST_SALES_LEDGER_GROUP", "Sales Accounts")
CGST_LEDGER_NAME = os.getenv("CGST_LEDGER_NAME", "CGST")
SGST_LEDGER_NAME = os.getenv("SGST_LEDGER_NAME", "SGST")
IGST_LEDGER_NAME = os.getenv("IGST_LEDGER_NAME", "IGST")
GST_BUYER_LEDGER_GROUP = os.getenv("GST_BUYER_LEDGER_GROUP", "Sundry Debtors")


def _validate_runtime_config() -> None:
    if APP_ENV != "production":
        return
    if CONNECTOR_MODE != "polling":
        raise RuntimeError("Production must use CONNECTOR_MODE=polling")
    if LOCAL_AGENT_BOOTSTRAP_ENABLED:
        raise RuntimeError("Production must set LOCAL_AGENT_BOOTSTRAP_ENABLED=false")
    if ALLOW_DEV_AUTH:
        raise RuntimeError("Production must set ALLOW_DEV_AUTH=false")
    if not GOOGLE_CLIENT_ID:
        raise RuntimeError("Production must set GOOGLE_CLIENT_ID")
    if not COOKIE_SECURE:
        raise RuntimeError("Production must set COOKIE_SECURE=true")
    if COOKIE_SAMESITE not in {"none", "lax", "strict"}:
        raise RuntimeError("COOKIE_SAMESITE must be one of: none, lax, strict")
    if COOKIE_SAMESITE != "none":
        raise RuntimeError("Production must set COOKIE_SAMESITE=none for cross-origin frontend sessions")


_validate_runtime_config()
