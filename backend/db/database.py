from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "tally_sales.db"


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
                pairing_status TEXT NOT NULL DEFAULT 'pending',
                last_seen_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_name TEXT NOT NULL,
                tally_url TEXT NOT NULL,
                sales_ledger_name TEXT NOT NULL,
                cash_ledger_name TEXT NOT NULL,
                upi_fallback_ledger_name TEXT NOT NULL,
                upi_fallback_group_name TEXT NOT NULL,
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
                payment_mode TEXT NOT NULL,
                voucher_date TEXT NOT NULL,
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
            """
        )


def _migrate_existing_tables(connection: sqlite3.Connection) -> None:
    for table, column, definition in [
        ("stock_items", "company_id", "INTEGER"),
        ("ledgers", "company_id", "INTEGER"),
        ("vouchers_log", "user_id", "INTEGER"),
        ("vouchers_log", "company_id", "INTEGER"),
        ("vouchers_log", "import_id", "INTEGER"),
        ("vouchers_log", "import_row_id", "INTEGER"),
        ("vouchers_log", "source_row_id", "TEXT"),
        ("vouchers_log", "source_fingerprint", "TEXT"),
    ]:
        _ensure_column(connection, table, column, definition)


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO companies (
                user_id, company_name, tally_url, sales_ledger_name, cash_ledger_name,
                upi_fallback_ledger_name, upi_fallback_group_name, setup_completed_at,
                local_agent_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                data["company_name"],
                data.get("tally_url", "http://localhost:9000"),
                data.get("sales_ledger_name", "Sales"),
                data.get("cash_ledger_name", "Cash"),
                data.get("upi_fallback_ledger_name", "UPI Sales"),
                data.get("upi_fallback_group_name", "Sundry Debtors"),
                now,
                data.get("local_agent_id"),
                now,
            ),
        )
        return get_company(cursor.lastrowid, user_id=user_id, connection=connection)


def list_companies(user_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM companies WHERE user_id = ? ORDER BY lower(company_name)",
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
        "sales_ledger_name",
        "cash_ledger_name",
        "upi_fallback_ledger_name",
        "upi_fallback_group_name",
        "local_agent_id",
    }
    updates = {key: value for key, value in data.items() if key in allowed and value is not None}
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


def create_pairing_token(user_id: int, device_name: str, token_hash: str, base_url: str | None = None) -> dict[str, Any]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO local_agents (user_id, device_name, base_url, pairing_token_hash)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, device_name, base_url, token_hash),
        )
        return get_local_agent(cursor.lastrowid, user_id=user_id, connection=connection)


def pair_local_agent(token_hash: str, device_name: str | None = None, base_url: str | None = None) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM local_agents
            WHERE pairing_token_hash = ?
              AND revoked_at IS NULL
            """,
            (token_hash,),
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


def replace_stock_items(names: Iterable[str], company_id: int | None = None) -> None:
    company_id = company_id or ensure_legacy_company()["id"]
    clean_names = sorted({name.strip() for name in names if name and name.strip()})
    with get_connection() as connection:
        connection.execute("DELETE FROM stock_items WHERE company_id = ?", (company_id,))
        connection.executemany(
            "INSERT OR IGNORE INTO stock_items (company_id, name) VALUES (?, ?)",
            [(company_id, name) for name in clean_names],
        )


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
            dict(row)
            for row in connection.execute(
                "SELECT * FROM stock_items WHERE company_id = ? ORDER BY name",
                (company_id,),
            )
        ]


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


def create_import(user_id: int, company_id: int, filename: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO imports (user_id, company_id, filename, status, row_count)
            VALUES (?, ?, ?, 'uploaded', ?)
            """,
            (user_id, company_id, filename, len(rows)),
        )
        import_id = cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO import_rows (
                import_id, company_id, source_row_id, product_name, price,
                payment_mode, voucher_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    import_id,
                    company_id,
                    str(row.get("source_row_id") or index + 1),
                    row["product_name"],
                    float(row["price"]),
                    row["payment_mode"],
                    row["voucher_date"],
                )
                for index, row in enumerate(rows)
            ],
        )
        return get_import(import_id, user_id=user_id, company_id=company_id, connection=connection)


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
            "cash_ledger_name": "Cash",
            "upi_fallback_ledger_name": "UPI Sales",
            "upi_fallback_group_name": "Sundry Debtors",
        },
    )


def random_token() -> str:
    return secrets.token_urlsafe(32)
