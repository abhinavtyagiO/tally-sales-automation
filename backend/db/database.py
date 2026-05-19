from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from backend import config


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(config.SQLITE_DB_PATH).expanduser() if config.SQLITE_DB_PATH else BASE_DIR / "tally_sales.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                google_sub TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                name TEXT,
                picture_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS local_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_name TEXT NOT NULL,
                base_url TEXT,
                pairing_token_hash TEXT UNIQUE,
                auth_token TEXT,
                pairing_status TEXT NOT NULL DEFAULT 'pending',
                last_seen_at TEXT,
                last_activity_at TEXT,
                last_error TEXT,
                setup_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_name TEXT NOT NULL,
                tally_url TEXT NOT NULL,
                supplier_gstin TEXT,
                supplier_state TEXT,
                gst_registration_name TEXT,
                gst_registration_type TEXT,
                gst_sales_ledger_name TEXT,
                cgst_ledger_name TEXT,
                sgst_ledger_name TEXT,
                igst_ledger_name TEXT,
                gst_buyer_ledger_group TEXT,
                sales_ledger_name TEXT NOT NULL,
                sales_ledger_group_name TEXT NOT NULL DEFAULT 'Sales Accounts',
                cash_ledger_name TEXT NOT NULL,
                cash_ledger_group_name TEXT NOT NULL DEFAULT 'Cash-in-Hand',
                upi_fallback_ledger_name TEXT NOT NULL,
                upi_fallback_group_name TEXT NOT NULL,
                payment_default_group_name TEXT NOT NULL DEFAULT 'Sundry Debtors',
                payment_ledger_mappings TEXT,
                setup_completed_at TEXT,
                last_sync_at TEXT,
                last_sync_status TEXT,
                last_selected_at TEXT,
                local_agent_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (local_agent_id) REFERENCES local_agents(id)
            );

            CREATE TABLE IF NOT EXISTS stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                group_name TEXT,
                category TEXT,
                base_unit TEXT,
                additional_unit TEXT,
                opening_balance TEXT,
                closing_balance TEXT,
                opening_value TEXT,
                closing_value TEXT,
                opening_rate TEXT,
                closing_rate TEXT,
                gst_type TEXT,
                gst_rate REAL,
                hsn_code TEXT,
                hsn_description TEXT,
                taxability TEXT,
                raw_json TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ledgers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                "group" TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                filename TEXT,
                import_type TEXT NOT NULL DEFAULT 'retail_sales',
                status TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                valid_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS import_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                source_row_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL,
                rate REAL,
                payment_mode TEXT NOT NULL,
                voucher_date TEXT NOT NULL,
                buyer_name TEXT,
                buyer_gstin TEXT,
                buyer_state TEXT,
                buyer_address TEXT,
                place_of_supply TEXT,
                taxable_amount REAL,
                gst_rate REAL,
                cgst_amount REAL,
                sgst_amount REAL,
                igst_amount REAL,
                total_amount REAL,
                validation_status TEXT NOT NULL DEFAULT 'pending',
                validation_error TEXT,
                voucher_preview TEXT,
                commit_status TEXT NOT NULL DEFAULT 'pending',
                commit_error TEXT,
                tally_response TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (import_id) REFERENCES imports(id) ON DELETE CASCADE,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS vouchers_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                company_id INTEGER,
                import_id INTEGER,
                import_row_id INTEGER,
                request TEXT NOT NULL,
                response TEXT,
                status TEXT NOT NULL,
                source_row_id TEXT,
                source_fingerprint TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (company_id) REFERENCES companies(id),
                FOREIGN KEY (import_id) REFERENCES imports(id),
                FOREIGN KEY (import_row_id) REFERENCES import_rows(id)
            );

            CREATE TABLE IF NOT EXISTS connector_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_id INTEGER,
                agent_id INTEGER NOT NULL,
                commit_run_id INTEGER,
                operation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                available_after TEXT,
                lease_expires_at TEXT,
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (commit_run_id) REFERENCES commit_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES local_agents(id)
            );

            CREATE TABLE IF NOT EXISTS commit_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                import_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                total_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (import_id) REFERENCES imports(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        _migrate_existing_tables(connection)
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_user_name
            ON companies(user_id, lower(company_name));

            CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_items_company_name
            ON stock_items(company_id, lower(name));

            CREATE UNIQUE INDEX IF NOT EXISTS idx_ledgers_company_name
            ON ledgers(company_id, lower(name));

            CREATE INDEX IF NOT EXISTS idx_vouchers_log_company_fingerprint
            ON vouchers_log(company_id, source_fingerprint);

            CREATE INDEX IF NOT EXISTS idx_connector_jobs_agent_status
            ON connector_jobs(agent_id, status, available_after, id);

            CREATE INDEX IF NOT EXISTS idx_connector_jobs_company_operation
            ON connector_jobs(company_id, operation, created_at);

            CREATE INDEX IF NOT EXISTS idx_connector_jobs_commit_run
            ON connector_jobs(commit_run_id, status, id);

            CREATE INDEX IF NOT EXISTS idx_commit_runs_import_status
            ON commit_runs(company_id, import_id, status, id);
            """
        )


def _migrate_existing_tables(connection: sqlite3.Connection) -> None:
    _migrate_master_table_uniqueness(connection)
    for table, column, definition in [
        ("stock_items", "company_id", "INTEGER"),
        ("ledgers", "company_id", "INTEGER"),
        ("companies", "sales_ledger_group_name", "TEXT"),
        ("companies", "supplier_gstin", "TEXT"),
        ("companies", "supplier_state", "TEXT"),
        ("companies", "gst_registration_name", "TEXT"),
        ("companies", "gst_registration_type", "TEXT"),
        ("companies", "gst_sales_ledger_name", "TEXT"),
        ("companies", "cgst_ledger_name", "TEXT"),
        ("companies", "sgst_ledger_name", "TEXT"),
        ("companies", "igst_ledger_name", "TEXT"),
        ("companies", "gst_buyer_ledger_group", "TEXT"),
        ("companies", "cash_ledger_group_name", "TEXT"),
        ("companies", "payment_default_group_name", "TEXT"),
        ("companies", "payment_ledger_mappings", "TEXT"),
        ("vouchers_log", "user_id", "INTEGER"),
        ("vouchers_log", "company_id", "INTEGER"),
        ("vouchers_log", "import_id", "INTEGER"),
        ("vouchers_log", "import_row_id", "INTEGER"),
        ("vouchers_log", "source_row_id", "TEXT"),
        ("vouchers_log", "source_fingerprint", "TEXT"),
        ("local_agents", "auth_token", "TEXT"),
        ("local_agents", "last_activity_at", "TEXT"),
        ("local_agents", "last_error", "TEXT"),
        ("local_agents", "setup_expires_at", "TEXT"),
        ("stock_items", "group_name", "TEXT"),
        ("stock_items", "category", "TEXT"),
        ("stock_items", "base_unit", "TEXT"),
        ("stock_items", "additional_unit", "TEXT"),
        ("stock_items", "opening_balance", "TEXT"),
        ("stock_items", "closing_balance", "TEXT"),
        ("stock_items", "opening_value", "TEXT"),
        ("stock_items", "closing_value", "TEXT"),
        ("stock_items", "opening_rate", "TEXT"),
        ("stock_items", "closing_rate", "TEXT"),
        ("stock_items", "gst_type", "TEXT"),
        ("stock_items", "gst_rate", "REAL"),
        ("stock_items", "hsn_code", "TEXT"),
        ("stock_items", "hsn_description", "TEXT"),
        ("stock_items", "taxability", "TEXT"),
        ("stock_items", "raw_json", "TEXT"),
        ("imports", "import_type", "TEXT NOT NULL DEFAULT 'retail_sales'"),
        ("import_rows", "quantity", "REAL"),
        ("import_rows", "rate", "REAL"),
        ("import_rows", "buyer_name", "TEXT"),
        ("import_rows", "buyer_gstin", "TEXT"),
        ("import_rows", "buyer_state", "TEXT"),
        ("import_rows", "buyer_address", "TEXT"),
        ("import_rows", "place_of_supply", "TEXT"),
        ("import_rows", "taxable_amount", "REAL"),
        ("import_rows", "gst_rate", "REAL"),
        ("import_rows", "cgst_amount", "REAL"),
        ("import_rows", "sgst_amount", "REAL"),
        ("import_rows", "igst_amount", "REAL"),
        ("import_rows", "total_amount", "REAL"),
        ("connector_jobs", "commit_run_id", "INTEGER"),
    ]:
        _ensure_column(connection, table, column, definition)
    connection.execute("UPDATE companies SET sales_ledger_group_name = COALESCE(sales_ledger_group_name, ?) ", (config.SALES_LEDGER_GROUP,))
    connection.execute("UPDATE companies SET cash_ledger_group_name = COALESCE(cash_ledger_group_name, ?) ", (config.CASH_LEDGER_GROUP,))
    connection.execute("UPDATE companies SET payment_default_group_name = COALESCE(payment_default_group_name, ?) ", (config.DEFAULT_PAYMENT_LEDGER_GROUP,))
    connection.execute("UPDATE companies SET gst_registration_name = COALESCE(gst_registration_name, ?) ", (config.GST_REGISTRATION_NAME,))
    connection.execute("UPDATE companies SET gst_registration_type = COALESCE(gst_registration_type, ?) ", (config.GST_REGISTRATION_TYPE,))
    connection.execute("UPDATE companies SET gst_sales_ledger_name = COALESCE(gst_sales_ledger_name, ?) ", (config.GST_SALES_LEDGER_NAME,))
    connection.execute("UPDATE companies SET cgst_ledger_name = COALESCE(cgst_ledger_name, ?) ", (config.CGST_LEDGER_NAME,))
    connection.execute("UPDATE companies SET sgst_ledger_name = COALESCE(sgst_ledger_name, ?) ", (config.SGST_LEDGER_NAME,))
    connection.execute("UPDATE companies SET igst_ledger_name = COALESCE(igst_ledger_name, ?) ", (config.IGST_LEDGER_NAME,))
    connection.execute("UPDATE companies SET gst_buyer_ledger_group = COALESCE(gst_buyer_ledger_group, ?) ", (config.GST_BUYER_LEDGER_GROUP,))


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_master_table_uniqueness(connection: sqlite3.Connection) -> None:
    for table in ("stock_items", "ledgers"):
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not row or "name TEXT NOT NULL UNIQUE" not in (row["sql"] or ""):
            continue

        old_table = f"{table}_legacy_unique"
        connection.execute(f"ALTER TABLE {table} RENAME TO {old_table}")
        if table == "stock_items":
            connection.execute(
                """
                CREATE TABLE stock_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    group_name TEXT,
                    category TEXT,
                    base_unit TEXT,
                    additional_unit TEXT,
                    opening_balance TEXT,
                    closing_balance TEXT,
                    opening_value TEXT,
                    closing_value TEXT,
                    opening_rate TEXT,
                    closing_rate TEXT,
                    gst_type TEXT,
                    gst_rate REAL,
                    hsn_code TEXT,
                    hsn_description TEXT,
                    taxability TEXT,
                    raw_json TEXT,
                    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                f"""
                INSERT OR IGNORE INTO stock_items (company_id, name)
                SELECT COALESCE(company_id, (SELECT id FROM companies ORDER BY id LIMIT 1)), name
                FROM {old_table}
                WHERE COALESCE(company_id, (SELECT id FROM companies ORDER BY id LIMIT 1)) IS NOT NULL
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE ledgers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    "group" TEXT,
                    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                f"""
                INSERT OR IGNORE INTO ledgers (company_id, name, "group")
                SELECT COALESCE(company_id, (SELECT id FROM companies ORDER BY id LIMIT 1)), name, "group"
                FROM {old_table}
                WHERE COALESCE(company_id, (SELECT id FROM companies ORDER BY id LIMIT 1)) IS NOT NULL
                """
            )
        connection.execute(f"DROP TABLE {old_table}")


def create_or_update_user(google_sub: str, email: str, name: str | None = None, picture_url: str | None = None) -> dict[str, Any]:
    now = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (google_sub, email, name, picture_url, last_login_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(google_sub) DO UPDATE SET
                email = excluded.email,
                name = excluded.name,
                picture_url = excluded.picture_url,
                last_login_at = excluded.last_login_at
            """,
            (google_sub, email, name, picture_url, now),
        )
        return get_user_by_google_sub(google_sub, connection=connection)


def get_user_by_google_sub(google_sub: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        row = connection.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
        return dict(row) if row else None
    finally:
        if close:
            connection.close()


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_session(user_id: int, token_hash: str, expires_at: str) -> dict[str, Any]:
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO sessions (user_id, session_token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )
        return get_session(cursor.lastrowid, connection=connection)


def get_session(session_id: int, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if close:
            connection.close()


def get_session_by_hash(token_hash: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT sessions.*, users.email, users.google_sub, users.name, users.picture_url
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE session_token_hash = ?
              AND revoked_at IS NULL
              AND expires_at > ?
            """,
            (token_hash, utc_now()),
        ).fetchone()
        return dict(row) if row else None


def revoke_session(token_hash: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE sessions SET revoked_at = ? WHERE session_token_hash = ?",
            (utc_now(), token_hash),
        )


def create_company(user_id: int, data: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    payment_ledger_mappings = data.get("payment_ledger_mappings")
    if payment_ledger_mappings is not None and not isinstance(payment_ledger_mappings, str):
        payment_ledger_mappings = json.dumps(payment_ledger_mappings)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO companies (
                user_id, company_name, tally_url, supplier_gstin, supplier_state,
                gst_registration_name, gst_registration_type, gst_sales_ledger_name,
                cgst_ledger_name, sgst_ledger_name, igst_ledger_name, gst_buyer_ledger_group,
                sales_ledger_name, sales_ledger_group_name,
                cash_ledger_name, cash_ledger_group_name, upi_fallback_ledger_name,
                upi_fallback_group_name, payment_default_group_name, payment_ledger_mappings,
                setup_completed_at, local_agent_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                data["company_name"],
                data.get("tally_url", config.TALLY_URL),
                data.get("supplier_gstin"),
                data.get("supplier_state"),
                data.get("gst_registration_name", config.GST_REGISTRATION_NAME),
                data.get("gst_registration_type", config.GST_REGISTRATION_TYPE),
                data.get("gst_sales_ledger_name", config.GST_SALES_LEDGER_NAME),
                data.get("cgst_ledger_name", config.CGST_LEDGER_NAME),
                data.get("sgst_ledger_name", config.SGST_LEDGER_NAME),
                data.get("igst_ledger_name", config.IGST_LEDGER_NAME),
                data.get("gst_buyer_ledger_group", config.GST_BUYER_LEDGER_GROUP),
                data.get("sales_ledger_name", config.SALES_LEDGER_NAME),
                data.get("sales_ledger_group_name", config.SALES_LEDGER_GROUP),
                data.get("cash_ledger_name", config.CASH_LEDGER_NAME),
                data.get("cash_ledger_group_name", config.CASH_LEDGER_GROUP),
                data.get("upi_fallback_ledger_name", config.UPI_FALLBACK_LEDGER),
                data.get("upi_fallback_group_name", config.UPI_FALLBACK_GROUP),
                data.get("payment_default_group_name", config.DEFAULT_PAYMENT_LEDGER_GROUP),
                payment_ledger_mappings,
                now,
                data.get("local_agent_id"),
                now,
            ),
        )
        return get_company(cursor.lastrowid, user_id=user_id, connection=connection)


def delete_company(company_id: int, user_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM companies WHERE id = ? AND user_id = ?", (company_id, user_id))
        return cursor.rowcount > 0


def list_companies(user_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM companies
                WHERE user_id = ?
                ORDER BY
                    CASE WHEN last_selected_at IS NULL THEN 1 ELSE 0 END,
                    last_selected_at DESC,
                    lower(company_name)
                """,
                (user_id,),
            )
        ]


def get_company(company_id: int, user_id: int | None = None, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        params: tuple[Any, ...]
        query = "SELECT * FROM companies WHERE id = ?"
        params = (company_id,)
        if user_id is not None:
            query += " AND user_id = ?"
            params = (company_id, user_id)
        row = connection.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        if close:
            connection.close()


def update_company(company_id: int, user_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    company = get_company(company_id, user_id)
    if not company:
        return None
    allowed = {
        "company_name",
        "tally_url",
        "supplier_gstin",
        "supplier_state",
        "gst_registration_name",
        "gst_registration_type",
        "gst_sales_ledger_name",
        "cgst_ledger_name",
        "sgst_ledger_name",
        "igst_ledger_name",
        "gst_buyer_ledger_group",
        "sales_ledger_name",
        "sales_ledger_group_name",
        "cash_ledger_name",
        "cash_ledger_group_name",
        "upi_fallback_ledger_name",
        "upi_fallback_group_name",
        "payment_default_group_name",
        "payment_ledger_mappings",
        "local_agent_id",
    }
    updates = {key: value for key, value in data.items() if key in allowed and value is not None}
    if "payment_ledger_mappings" in updates and not isinstance(updates["payment_ledger_mappings"], str):
        updates["payment_ledger_mappings"] = json.dumps(updates["payment_ledger_mappings"])
    if not updates:
        return company
    invalidate = any(key in updates for key in {"company_name", "tally_url"})
    updates["updated_at"] = utc_now()
    if invalidate:
        updates["last_sync_at"] = None
        updates["last_sync_status"] = "invalidated"
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with get_connection() as connection:
        connection.execute(
            f"UPDATE companies SET {assignments} WHERE id = ? AND user_id = ?",
            (*updates.values(), company_id, user_id),
        )
        if invalidate:
            clear_company_masters(company_id, connection=connection)
        return get_company(company_id, user_id=user_id, connection=connection)


def select_company(company_id: int, user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE companies SET last_selected_at = ? WHERE id = ? AND user_id = ?",
            (utc_now(), company_id, user_id),
        )
        return get_company(company_id, user_id=user_id, connection=connection)


def clear_company_masters(company_id: int, connection: sqlite3.Connection | None = None) -> None:
    close = connection is None
    connection = connection or get_connection()
    try:
        connection.execute("DELETE FROM stock_items WHERE company_id = ?", (company_id,))
        connection.execute("DELETE FROM ledgers WHERE company_id = ?", (company_id,))
    finally:
        if close:
            connection.close()


def set_company_sync(company_id: int, status: str, synced_at: str | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE companies SET last_sync_status = ?, last_sync_at = ? WHERE id = ?",
            (status, synced_at, company_id),
        )


def create_pairing_token(
    user_id: int,
    device_name: str,
    token_hash: str,
    base_url: str | None = None,
    auth_token: str | None = None,
    setup_expires_at: str | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO local_agents (user_id, device_name, base_url, pairing_token_hash, auth_token, setup_expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, device_name, base_url, token_hash, auth_token, setup_expires_at),
        )
        return get_local_agent(cursor.lastrowid, user_id=user_id, connection=connection)


def pair_local_agent(token_hash: str, device_name: str | None = None, base_url: str | None = None) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM local_agents
            WHERE pairing_token_hash = ?
              AND revoked_at IS NULL
              AND (setup_expires_at IS NULL OR setup_expires_at > ?)
            """,
            (token_hash, utc_now()),
        ).fetchone()
        if not row:
            return None
        agent = dict(row)
        connection.execute(
            """
            UPDATE local_agents
            SET pairing_status = 'paired',
                device_name = COALESCE(?, device_name),
                base_url = COALESCE(?, base_url),
                last_seen_at = ?
            WHERE id = ?
            """,
            (device_name, base_url, utc_now(), agent["id"]),
        )
        return get_local_agent(agent["id"], connection=connection)


def heartbeat_local_agent(agent_id: int, user_id: int | None = None, base_url: str | None = None) -> dict[str, Any] | None:
    agent = get_local_agent(agent_id, user_id=user_id)
    if not agent or agent.get("revoked_at"):
        return None
    with get_connection() as connection:
        connection.execute(
            "UPDATE local_agents SET last_seen_at = ?, base_url = COALESCE(?, base_url) WHERE id = ?",
            (utc_now(), base_url, agent_id),
        )
        return get_local_agent(agent_id, user_id=user_id, connection=connection)


def update_local_agent_activity(agent_id: int, error_message: str | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE local_agents
            SET last_activity_at = ?,
                last_error = ?
            WHERE id = ?
            """,
            (utc_now(), error_message, agent_id),
        )


def revoke_local_agent(agent_id: int, user_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE local_agents SET revoked_at = ? WHERE id = ? AND user_id = ?",
            (utc_now(), agent_id, user_id),
        )
        return cursor.rowcount > 0


def get_local_agent(agent_id: int, user_id: int | None = None, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        query = "SELECT * FROM local_agents WHERE id = ?"
        params: tuple[Any, ...] = (agent_id,)
        if user_id is not None:
            query += " AND user_id = ?"
            params = (agent_id, user_id)
        row = connection.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        if close:
            connection.close()


def get_active_local_agent(user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM local_agents
            WHERE user_id = ?
              AND revoked_at IS NULL
              AND pairing_status = 'paired'
              AND base_url IS NOT NULL
            ORDER BY
              CASE WHEN last_seen_at IS NULL THEN 1 ELSE 0 END,
              last_seen_at DESC,
              id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_latest_local_agent(user_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM local_agents
            WHERE user_id = ?
              AND revoked_at IS NULL
            ORDER BY
              CASE WHEN last_seen_at IS NULL THEN 1 ELSE 0 END,
              last_seen_at DESC,
              id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def create_connector_job(
    user_id: int,
    company_id: int | None,
    agent_id: int,
    operation: str,
    payload: dict[str, Any],
    available_after: str | None = None,
    commit_run_id: int | None = None,
) -> dict[str, Any]:
    now = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO connector_jobs (
                user_id, company_id, agent_id, commit_run_id, operation, payload_json,
                status, available_after, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
            """,
            (user_id, company_id, agent_id, commit_run_id, operation, json.dumps(payload), available_after, now, now),
        )
        return get_connector_job(cursor.lastrowid, connection=connection)


def get_connector_job(job_id: int, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        row = connection.execute("SELECT * FROM connector_jobs WHERE id = ?", (job_id,)).fetchone()
        return _decode_connector_job(dict(row)) if row else None
    finally:
        if close:
            connection.close()


def lease_next_connector_job(agent_id: int, lease_expires_at: str) -> dict[str, Any] | None:
    now = utc_now()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM connector_jobs
            WHERE agent_id = ?
              AND status = 'queued'
              AND (available_after IS NULL OR available_after <= ?)
            ORDER BY id
            LIMIT 1
            """,
            (agent_id, now),
        ).fetchone()
        if not row:
            return None
        job_id = int(row["id"])
        connection.execute(
            """
            UPDATE connector_jobs
            SET status = 'leased',
                attempt_count = attempt_count + 1,
                lease_expires_at = ?,
                updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (lease_expires_at, now, job_id),
        )
        return get_connector_job(job_id, connection=connection)


def complete_connector_job(job_id: int, agent_id: int, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    now = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE connector_jobs
            SET status = 'completed',
                result_json = ?,
                error_message = NULL,
                completed_at = ?,
                updated_at = ?
            WHERE id = ? AND agent_id = ? AND status = 'leased'
            """,
            (json.dumps(result or {}), now, now, job_id, agent_id),
        )
        if cursor.rowcount == 0:
            return None
        return get_connector_job(job_id, connection=connection)


def fail_connector_job(job_id: int, agent_id: int, error_message: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    now = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE connector_jobs
            SET status = 'failed',
                result_json = ?,
                error_message = ?,
                completed_at = ?,
                updated_at = ?
            WHERE id = ? AND agent_id = ? AND status = 'leased'
            """,
            (json.dumps(result or {}), error_message, now, now, job_id, agent_id),
        )
        if cursor.rowcount == 0:
            return None
        return get_connector_job(job_id, connection=connection)


def get_latest_connector_job(company_id: int, operation: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM connector_jobs
            WHERE company_id = ? AND operation = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (company_id, operation),
        ).fetchone()
        return _decode_connector_job(dict(row)) if row else None


def get_latest_connector_job_for_user(user_id: int, operation: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM connector_jobs
            WHERE user_id = ? AND operation = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, operation),
        ).fetchone()
        return _decode_connector_job(dict(row)) if row else None


def list_connector_jobs_for_commit_run(commit_run_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return [
            _decode_connector_job(dict(row))
            for row in connection.execute(
                """
                SELECT * FROM connector_jobs
                WHERE commit_run_id = ?
                ORDER BY id
                """,
                (commit_run_id,),
            )
        ]


def list_recent_connector_jobs_for_agent(agent_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return [
            _decode_connector_job(dict(row))
            for row in connection.execute(
                """
                SELECT * FROM connector_jobs
                WHERE agent_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (agent_id, limit),
            )
        ]


def _decode_connector_job(job: dict[str, Any]) -> dict[str, Any]:
    for source, target in (("payload_json", "payload"), ("result_json", "result")):
        raw = job.get(source)
        if raw:
            try:
                job[target] = json.loads(raw)
            except (TypeError, ValueError):
                job[target] = {}
        else:
            job[target] = {}
    return job


def replace_stock_items(items: Iterable[str | dict[str, Any]], company_id: int | None = None) -> None:
    company_id = company_id or ensure_legacy_company()["id"]
    stock_items = []
    seen = set()
    for item in items:
        normalized = _normalize_stock_item(item)
        name = normalized.get("name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        stock_items.append(normalized)
    stock_items.sort(key=lambda item: item["name"].lower())
    with get_connection() as connection:
        connection.execute("DELETE FROM stock_items WHERE company_id = ?", (company_id,))
        connection.executemany(
            """
            INSERT OR IGNORE INTO stock_items (
                company_id, name, group_name, category, base_unit, additional_unit,
                opening_balance, closing_balance, opening_value, closing_value,
                opening_rate, closing_rate, gst_type, gst_rate, hsn_code,
                hsn_description, taxability, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    company_id,
                    item["name"],
                    item.get("group_name"),
                    item.get("category"),
                    item.get("base_unit"),
                    item.get("additional_unit"),
                    item.get("opening_balance"),
                    item.get("closing_balance"),
                    item.get("opening_value"),
                    item.get("closing_value"),
                    item.get("opening_rate"),
                    item.get("closing_rate"),
                    item.get("gst_type"),
                    item.get("gst_rate"),
                    item.get("hsn_code"),
                    item.get("hsn_description"),
                    item.get("taxability"),
                    json.dumps(item.get("raw")) if item.get("raw") is not None else None,
                )
                for item in stock_items
            ],
        )


def _normalize_stock_item(item: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, str):
        return {"name": item.strip()}
    name = str(item.get("name") or item.get("Name") or "").strip()
    return {
        "name": name,
        "group_name": _clean_optional(item.get("group_name") or item.get("group") or item.get("Parent")),
        "category": _clean_optional(item.get("category") or item.get("StockCategory") or item.get("Category")),
        "base_unit": _clean_optional(item.get("base_unit") or item.get("baseUnit") or item.get("BaseUnits")),
        "additional_unit": _clean_optional(item.get("additional_unit") or item.get("additionalUnit") or item.get("AdditionalUnits")),
        "opening_balance": _clean_optional(item.get("opening_balance") or item.get("openingBalance") or item.get("OpeningBalance")),
        "closing_balance": _clean_optional(item.get("closing_balance") or item.get("closingBalance") or item.get("ClosingBalance")),
        "opening_value": _clean_optional(item.get("opening_value") or item.get("openingValue") or item.get("OpeningValue")),
        "closing_value": _clean_optional(item.get("closing_value") or item.get("closingValue") or item.get("ClosingValue")),
        "opening_rate": _clean_optional(item.get("opening_rate") or item.get("openingRate") or item.get("OpeningRate")),
        "closing_rate": _clean_optional(item.get("closing_rate") or item.get("closingRate") or item.get("ClosingRate")),
        "gst_type": _clean_optional(item.get("gst_type") or item.get("gstType") or item.get("GSTTypeOfSupply")),
        "gst_rate": _clean_float(item.get("gst_rate") or item.get("gstRate") or item.get("GSTRate")),
        "hsn_code": _clean_optional(item.get("hsn_code") or item.get("hsnCode") or item.get("GSTHSNName") or item.get("GSTHSNSACCode") or item.get("HSNCode")),
        "hsn_description": _clean_optional(item.get("hsn_description") or item.get("hsnDescription") or item.get("GSTHSNDescription")),
        "taxability": _clean_optional(item.get("taxability") or item.get("GSTOVRDNTaxability") or item.get("Taxability")),
        "raw": item.get("raw") or item.get("Raw") or item,
    }


def _clean_optional(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _clean_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def replace_ledgers(ledgers: Iterable[dict[str, Any]], company_id: int | None = None) -> None:
    company_id = company_id or ensure_legacy_company()["id"]
    rows = []
    seen = set()
    for ledger in ledgers:
        name = str(ledger.get("name", "")).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append((company_id, name, ledger.get("group") or ledger.get("group_name")))

    with get_connection() as connection:
        connection.execute("DELETE FROM ledgers WHERE company_id = ?", (company_id,))
        connection.executemany(
            "INSERT OR IGNORE INTO ledgers (company_id, name, \"group\") VALUES (?, ?, ?)",
            rows,
        )


def upsert_ledger(name: str, group_name: str | None, company_id: int | None = None) -> None:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO ledgers (company_id, name, "group")
            VALUES (?, ?, ?)
            ON CONFLICT(company_id, lower(name)) DO UPDATE SET "group" = excluded."group"
            """,
            (company_id, name, group_name),
        )


def get_stock_item_by_name(name: str, company_id: int | None = None) -> sqlite3.Row | None:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM stock_items WHERE company_id = ? AND lower(name) = lower(?)",
            (company_id, name),
        ).fetchone()


def get_ledger_by_name(name: str, company_id: int | None = None) -> sqlite3.Row | None:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM ledgers WHERE company_id = ? AND lower(name) = lower(?)",
            (company_id, name),
        ).fetchone()


def list_stock_items(company_id: int | None = None) -> list[dict[str, Any]]:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        return [
            _decode_stock_item(row)
            for row in connection.execute(
                "SELECT * FROM stock_items WHERE company_id = ? ORDER BY name",
                (company_id,),
            )
        ]


def _decode_stock_item(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    raw_json = item.pop("raw_json", None)
    try:
        item["raw"] = json.loads(raw_json) if raw_json else None
    except json.JSONDecodeError:
        item["raw"] = None
    return item


def list_ledgers(company_id: int | None = None) -> list[dict[str, Any]]:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM ledgers WHERE company_id = ? ORDER BY name",
                (company_id,),
            )
        ]


def create_import(user_id: int, company_id: int, filename: str | None, rows: list[dict[str, Any]], import_type: str = "retail_sales") -> dict[str, Any]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO imports (user_id, company_id, filename, import_type, status, row_count)
            VALUES (?, ?, ?, ?, 'uploaded', ?)
            """,
            (user_id, company_id, filename, import_type, len(rows)),
        )
        import_id = cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO import_rows (
                import_id, company_id, source_row_id, product_name, price,
                quantity, rate, payment_mode, voucher_date, buyer_name, buyer_gstin,
                buyer_state, buyer_address, place_of_supply, taxable_amount, gst_rate,
                cgst_amount, sgst_amount, igst_amount, total_amount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    import_id,
                    company_id,
                    str(row.get("source_row_id") or index + 1),
                    row["product_name"],
                    float(row.get("price") or row.get("rate") or 0),
                    _optional_float(row.get("quantity")),
                    _optional_float(row.get("rate")),
                    row["payment_mode"],
                    row["voucher_date"],
                    row.get("buyer_name"),
                    row.get("buyer_gstin"),
                    row.get("buyer_state"),
                    row.get("buyer_address"),
                    row.get("place_of_supply"),
                    _optional_float(row.get("taxable_amount")),
                    _optional_float(row.get("gst_rate")),
                    _optional_float(row.get("cgst_amount")),
                    _optional_float(row.get("sgst_amount")),
                    _optional_float(row.get("igst_amount")),
                    _optional_float(row.get("total_amount")),
                )
                for index, row in enumerate(rows)
            ],
        )
        return get_import(import_id, user_id=user_id, company_id=company_id, connection=connection)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def get_import(import_id: int, user_id: int, company_id: int, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM imports WHERE id = ? AND user_id = ? AND company_id = ?",
            (import_id, user_id, company_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        if close:
            connection.close()


def list_imports(user_id: int, company_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM imports WHERE user_id = ? AND company_id = ? ORDER BY id DESC",
                (user_id, company_id),
            )
        ]


def list_import_rows(import_id: int, company_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return [
            _decode_import_row(row)
            for row in connection.execute(
                "SELECT * FROM import_rows WHERE import_id = ? AND company_id = ? ORDER BY id",
                (import_id, company_id),
            )
        ]


def update_import_row_validation(import_row_id: int, status: str, error: str | None, voucher_preview: dict[str, Any] | None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE import_rows
            SET validation_status = ?, validation_error = ?, voucher_preview = ?
            WHERE id = ?
            """,
            (status, error, json.dumps(voucher_preview) if voucher_preview else None, import_row_id),
        )


def update_import_row_gst_totals(import_row_id: int, voucher_preview: dict[str, Any] | None) -> None:
    if not voucher_preview:
        return
    tax = voucher_preview.get("TaxSplit") or {}
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE import_rows
            SET taxable_amount = ?, gst_rate = ?, cgst_amount = ?, sgst_amount = ?,
                igst_amount = ?, total_amount = ?
            WHERE id = ?
            """,
            (
                tax.get("taxable_amount") or voucher_preview.get("TaxableAmount"),
                tax.get("gst_rate"),
                tax.get("cgst_amount"),
                tax.get("sgst_amount"),
                tax.get("igst_amount"),
                tax.get("invoice_total") or voucher_preview.get("InvoiceTotal"),
                import_row_id,
            ),
        )


def update_import_counts(import_id: int) -> None:
    with get_connection() as connection:
        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                SUM(CASE WHEN validation_status = 'valid' THEN 1 ELSE 0 END) AS valid_count,
                SUM(CASE WHEN validation_status = 'invalid' THEN 1 ELSE 0 END) AS error_count
            FROM import_rows
            WHERE import_id = ?
            """,
            (import_id,),
        ).fetchone()
        status = "processed" if counts["row_count"] else "uploaded"
        connection.execute(
            """
            UPDATE imports
            SET row_count = ?, valid_count = ?, error_count = ?, status = ?
            WHERE id = ?
            """,
            (counts["row_count"], counts["valid_count"] or 0, counts["error_count"] or 0, status, import_id),
        )


def update_import_row_commit(import_row_id: int, status: str, error: str | None, tally_response: Any = None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE import_rows
            SET commit_status = ?, commit_error = ?, tally_response = ?
            WHERE id = ?
            """,
            (status, error, json.dumps(tally_response) if tally_response is not None else None, import_row_id),
        )


def mark_import_completed(import_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE imports SET status = 'committed', completed_at = ? WHERE id = ?",
            (utc_now(), import_id),
        )


def create_commit_run(user_id: int, company_id: int, import_id: int, total_count: int = 0) -> dict[str, Any]:
    now = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO commit_runs (user_id, company_id, import_id, status, total_count, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, ?, ?)
            """,
            (user_id, company_id, import_id, total_count, now, now),
        )
        return get_commit_run(cursor.lastrowid, user_id=user_id, company_id=company_id, connection=connection)


def get_commit_run(run_id: int, user_id: int, company_id: int, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    close = connection is None
    connection = connection or get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM commit_runs WHERE id = ? AND user_id = ? AND company_id = ?",
            (run_id, user_id, company_id),
        ).fetchone()
        return _decode_commit_run(dict(row)) if row else None
    finally:
        if close:
            connection.close()


def get_active_commit_run(user_id: int, company_id: int, import_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM commit_runs
            WHERE user_id = ? AND company_id = ? AND import_id = ?
              AND status IN ('queued', 'processing')
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, company_id, import_id),
        ).fetchone()
        return _decode_commit_run(dict(row)) if row else None


def update_commit_run_status(run_id: int, status: str, total_count: int | None = None) -> None:
    updates: dict[str, Any] = {"status": status, "updated_at": utc_now()}
    if total_count is not None:
        updates["total_count"] = total_count
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with get_connection() as connection:
        connection.execute(f"UPDATE commit_runs SET {assignments} WHERE id = ?", (*updates.values(), run_id))


def complete_commit_run(run_id: int, summary: dict[str, Any]) -> dict[str, Any] | None:
    now = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE commit_runs
            SET status = 'completed',
                total_count = ?,
                success_count = ?,
                failed_count = ?,
                result_json = ?,
                error_message = NULL,
                completed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                len(summary.get("results") or []),
                summary.get("success_count", 0),
                summary.get("failed_count", 0),
                json.dumps(summary),
                now,
                now,
                run_id,
            ),
        )
        row = connection.execute("SELECT * FROM commit_runs WHERE id = ?", (run_id,)).fetchone()
        return _decode_commit_run(dict(row)) if row else None


def refresh_commit_run_from_rows(run_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        run_row = connection.execute("SELECT * FROM commit_runs WHERE id = ?", (run_id,)).fetchone()
        if not run_row:
            return None
        run = dict(run_row)
        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN commit_status = 'success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN commit_status = 'failed' THEN 1 ELSE 0 END) AS failed_count
            FROM import_rows
            WHERE import_id = ?
              AND validation_status = 'valid'
            """,
            (run["import_id"],),
        ).fetchone()
        total = counts["total_count"] or 0
        success = counts["success_count"] or 0
        failed = counts["failed_count"] or 0
        jobs = list_connector_jobs_for_commit_run(run_id)
        job_terminal = jobs and all(job["status"] in {"completed", "failed"} for job in jobs)
        status = "completed" if job_terminal and success + failed >= total else "processing"
        completed_at = utc_now() if status == "completed" else None
        result = {
            "results": [
                {"job_id": job["id"], "status": "success" if job["status"] == "completed" else "failed", "error": job.get("error_message")}
                for job in jobs
                if job["status"] in {"completed", "failed"}
            ],
            "rows": list_import_rows(run["import_id"], run["company_id"]),
            "success_count": success,
            "failed_count": failed,
        }
        connection.execute(
            """
            UPDATE commit_runs
            SET status = ?,
                total_count = ?,
                success_count = ?,
                failed_count = ?,
                result_json = ?,
                completed_at = COALESCE(completed_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (status, total, success, failed, json.dumps(result), completed_at, utc_now(), run_id),
        )
        if status == "completed":
            connection.execute(
                "UPDATE imports SET status = 'committed', completed_at = COALESCE(completed_at, ?) WHERE id = ?",
                (completed_at, run["import_id"]),
            )
        row = connection.execute("SELECT * FROM commit_runs WHERE id = ?", (run_id,)).fetchone()
        return _decode_commit_run(dict(row)) if row else None


def fail_commit_run(run_id: int, error_message: str) -> dict[str, Any] | None:
    now = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE commit_runs
            SET status = 'failed',
                error_message = ?,
                completed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (error_message, now, now, run_id),
        )
        row = connection.execute("SELECT * FROM commit_runs WHERE id = ?", (run_id,)).fetchone()
        return _decode_commit_run(dict(row)) if row else None


def _decode_commit_run(run: dict[str, Any]) -> dict[str, Any]:
    raw = run.get("result_json")
    if raw:
        try:
            run["result"] = json.loads(raw)
        except (TypeError, ValueError):
            run["result"] = {}
    else:
        run["result"] = {}
    return run


def _decode_import_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    if data.get("voucher_preview"):
        data["voucher_preview"] = json.loads(data["voucher_preview"])
    if data.get("tally_response"):
        data["tally_response"] = json.loads(data["tally_response"])
    return data


def set_metadata(key: str, value: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def get_metadata(key: str) -> str | None:
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def log_voucher(
    request: dict[str, Any],
    response: Any,
    status: str,
    source: Optional[dict[str, Any]] = None,
) -> None:
    source = source or {}
    import_id = source.get("import_id") if isinstance(source.get("import_id"), int) else None
    import_row_id = source.get("import_row_id") if isinstance(source.get("import_row_id"), int) else None
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO vouchers_log (
                user_id, company_id, import_id, import_row_id, request, response,
                status, source_row_id, source_fingerprint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.get("user_id"),
                source.get("company_id"),
                import_id,
                import_row_id,
                json.dumps(request),
                json.dumps(response),
                status,
                source.get("source_row_id"),
                source.get("source_fingerprint"),
            ),
        )


def successful_fingerprint_exists(source_fingerprint: str, company_id: int | None = None) -> bool:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM vouchers_log
            WHERE source_fingerprint = ?
              AND company_id = ?
              AND status = 'success'
            LIMIT 1
            """,
            (source_fingerprint, company_id),
        ).fetchone()
        return row is not None


def list_voucher_logs(company_id: int | None = None) -> list[dict[str, Any]]:
    company_id = company_id or ensure_legacy_company()["id"]
    with get_connection() as connection:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, user_id, company_id, import_id, import_row_id, request,
                       response, status, source_row_id, source_fingerprint, created_at
                FROM vouchers_log
                WHERE company_id = ?
                ORDER BY id
                """,
                (company_id,),
            )
        ]


def ensure_legacy_company() -> dict[str, Any]:
    user = get_user_by_google_sub("legacy-local")
    if not user:
        user = create_or_update_user("legacy-local", "legacy@example.test", "Legacy Local User")
    companies = list_companies(user["id"])
    if companies:
        return companies[0]
    return create_company(
        user["id"],
        {
            "company_name": "Legacy Local Company",
            "tally_url": "http://localhost:9000",
            "sales_ledger_name": "Sales",
            "sales_ledger_group_name": "Sales Accounts",
            "cash_ledger_name": "Cash",
            "cash_ledger_group_name": "Cash-in-Hand",
            "upi_fallback_ledger_name": "UPI Sales",
            "upi_fallback_group_name": "Sundry Debtors",
            "payment_default_group_name": "Sundry Debtors",
        },
    )


def random_token() -> str:
    return secrets.token_urlsafe(32)
