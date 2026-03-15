from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from common import (
    DB_PATH,
    RESEARCH_DIR,
    detect_market,
    display_code_to_symbol,
    ensure_runtime_layout,
    format_display_code,
    infer_cn_exchange,
    normalize_symbol,
    read_text_excerpt,
    utc_now_iso,
)


BASE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS securities (
    security_id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL,
    display_code TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    company_name_zh TEXT NOT NULL DEFAULT '',
    name_pinyin TEXT NOT NULL DEFAULT '',
    name_pinyin_abbr TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(market, symbol),
    UNIQUE(display_code)
);

CREATE TABLE IF NOT EXISTS dossiers (
    ticker TEXT PRIMARY KEY,
    company_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    thesis_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    traded_at TEXT NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    source_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    remaining_quantity REAL NOT NULL,
    cost_basis REAL NOT NULL,
    opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS charters (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL CHECK(status IN ('unset', 'draft', 'active', 'superseded')),
    raw_markdown TEXT NOT NULL,
    compiled_rules_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS charter_candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    candidate_text TEXT NOT NULL,
    candidate_kind TEXT NOT NULL CHECK(candidate_kind IN ('style', 'sizing', 'ban', 'add', 'trim', 'exit', 'risk', 'reflection')),
    confidence REAL NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN ('pending', 'accepted', 'rejected', 'merged')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    period_end TEXT NOT NULL DEFAULT '',
    filed_at TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    UNIQUE(source_url, sha256)
);

CREATE TABLE IF NOT EXISTS advice_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    output_markdown TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_date TEXT NOT NULL UNIQUE,
    summary_path TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    document_alert_count INTEGER NOT NULL,
    position_alert_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    ensure_runtime_layout()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def add_column_if_missing(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    if name in table_columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _ensure_columns(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "dossiers", "security_id", "security_id INTEGER")
    add_column_if_missing(conn, "dossiers", "market", "market TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "dossiers", "exchange", "exchange TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "dossiers", "currency", "currency TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "dossiers", "display_code", "display_code TEXT NOT NULL DEFAULT ''")

    add_column_if_missing(conn, "trade_events", "security_id", "security_id INTEGER")
    add_column_if_missing(conn, "trade_events", "market", "market TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "trade_events", "currency", "currency TEXT NOT NULL DEFAULT ''")

    add_column_if_missing(conn, "position_lots", "security_id", "security_id INTEGER")
    add_column_if_missing(conn, "position_lots", "market", "market TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "position_lots", "currency", "currency TEXT NOT NULL DEFAULT ''")

    add_column_if_missing(conn, "documents", "security_id", "security_id INTEGER")
    add_column_if_missing(conn, "documents", "market", "market TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "documents", "exchange", "exchange TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "documents", "document_category", "document_category TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "documents", "document_subtype", "document_subtype TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "documents", "title", "title TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "documents", "source_platform", "source_platform TEXT NOT NULL DEFAULT ''")

    add_column_if_missing(conn, "advice_runs", "security_id", "security_id INTEGER")
    add_column_if_missing(conn, "advice_runs", "market", "market TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "advice_runs", "currency", "currency TEXT NOT NULL DEFAULT ''")


def infer_security_identity(value: str, company_name: str = "") -> dict[str, str]:
    normalized = normalize_symbol(value)
    market = detect_market(normalized)
    if market == "CN":
        symbol = display_code_to_symbol(normalized)
        exchange = infer_cn_exchange(normalized)
        display_code = format_display_code("CN", symbol, exchange)
        return {
            "market": "CN",
            "exchange": exchange,
            "symbol": symbol,
            "display_code": display_code,
            "company_name": company_name or display_code,
            "company_name_zh": company_name if company_name and not company_name.isascii() else "",
            "currency": "CNY",
            "source": "legacy-import",
        }
    symbol = normalized.upper()
    return {
        "market": "US",
        "exchange": "",
        "symbol": symbol,
        "display_code": symbol,
        "company_name": company_name or symbol,
        "company_name_zh": "",
        "currency": "USD",
        "source": "legacy-import",
    }


def upsert_security(conn: sqlite3.Connection, payload: dict[str, str]) -> int:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO securities
        (market, exchange, symbol, display_code, company_name, company_name_zh, name_pinyin, name_pinyin_abbr, currency, status, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(market, symbol) DO UPDATE SET
            exchange = excluded.exchange,
            display_code = excluded.display_code,
            company_name = CASE WHEN excluded.company_name != '' THEN excluded.company_name ELSE securities.company_name END,
            company_name_zh = CASE WHEN excluded.company_name_zh != '' THEN excluded.company_name_zh ELSE securities.company_name_zh END,
            currency = excluded.currency,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            payload["market"],
            payload["exchange"],
            payload["symbol"],
            payload["display_code"],
            payload["company_name"],
            payload.get("company_name_zh", ""),
            payload.get("name_pinyin", ""),
            payload.get("name_pinyin_abbr", ""),
            payload["currency"],
            payload.get("source", "manual"),
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT security_id FROM securities WHERE market = ? AND symbol = ?",
        (payload["market"], payload["symbol"]),
    ).fetchone()
    return int(row["security_id"])


def classify_existing_document(doc_type: str, source_url: str, local_path: str) -> tuple[str, str, str]:
    title = Path(local_path).name if local_path else doc_type
    source_platform = "sec" if "sec.gov" in source_url else "local"
    doc_type_upper = (doc_type or "").upper()
    if doc_type_upper == "10-K":
        return "financial_report", "annual_report", title
    if doc_type_upper == "10-Q":
        period = Path(local_path).stem.lower()
        if "03-31" in period:
            return "financial_report", "q1_report", title
        if "09-30" in period:
            return "financial_report", "q3_report", title
        return "financial_report", "semiannual_report", title
    if doc_type_upper == "8-K":
        return "material_event", "other_material", title
    if doc_type_upper.startswith("EX-99"):
        return "material_event", "other_material", title
    return "other_material", "other_material", title


def _backfill_security_links(conn: sqlite3.Connection) -> None:
    dossiers = conn.execute("SELECT ticker, company_name, security_id, market, exchange, currency, display_code FROM dossiers").fetchall()
    for dossier in dossiers:
        if dossier["security_id"]:
            security = conn.execute(
                "SELECT security_id, market, exchange, currency, display_code FROM securities WHERE security_id = ?",
                (dossier["security_id"],),
            ).fetchone()
        if not security:
            identity = infer_security_identity(dossier["display_code"] or dossier["ticker"], dossier["company_name"])
            security_id = upsert_security(conn, identity)
            security = conn.execute(
                "SELECT security_id, market, exchange, currency, display_code FROM securities WHERE security_id = ?",
                (security_id,),
            ).fetchone()
        if (
            dossier["security_id"]
            and dossier["market"] == security["market"]
            and dossier["exchange"] == security["exchange"]
            and dossier["currency"] == security["currency"]
            and dossier["display_code"] == security["display_code"]
        ):
            continue
        conn.execute(
            """
            UPDATE dossiers
            SET security_id = ?, market = ?, exchange = ?, currency = ?, display_code = ?
            WHERE ticker = ?
            """,
            (
                security["security_id"],
                security["market"],
                security["exchange"],
                security["currency"],
                security["display_code"],
                dossier["ticker"],
            ),
        )

    dossiers_by_ticker = {
        row["ticker"]: dict(row)
        for row in conn.execute(
            "SELECT ticker, security_id, market, exchange, currency, display_code FROM dossiers"
        ).fetchall()
    }

    for row in conn.execute("SELECT id, ticker, security_id, market, currency FROM trade_events").fetchall():
        dossier = dossiers_by_ticker.get(row["ticker"])
        if not dossier:
            continue
        if row["security_id"] == dossier["security_id"] and row["market"] == dossier["market"] and row["currency"] == dossier["currency"]:
            continue
        conn.execute(
            "UPDATE trade_events SET security_id = ?, market = ?, currency = ? WHERE id = ?",
            (dossier["security_id"], dossier["market"], dossier["currency"], row["id"]),
        )

    for row in conn.execute("SELECT id, ticker, security_id, market, currency FROM position_lots").fetchall():
        dossier = dossiers_by_ticker.get(row["ticker"])
        if not dossier:
            continue
        if row["security_id"] == dossier["security_id"] and row["market"] == dossier["market"] and row["currency"] == dossier["currency"]:
            continue
        conn.execute(
            "UPDATE position_lots SET security_id = ?, market = ?, currency = ? WHERE id = ?",
            (dossier["security_id"], dossier["market"], dossier["currency"], row["id"]),
        )

    for row in conn.execute(
        "SELECT id, ticker, security_id, market, exchange, document_category, document_subtype, title, source_platform, doc_type, source_url, local_path FROM documents"
    ).fetchall():
        dossier = dossiers_by_ticker.get(row["ticker"])
        if not dossier:
            continue
        if (
            row["security_id"] == dossier["security_id"]
            and row["market"] == dossier["market"]
            and row["exchange"] == dossier["exchange"]
            and row["document_category"]
            and row["source_platform"]
        ):
            continue
        category, subtype, title = classify_existing_document(row["doc_type"], row["source_url"], row["local_path"])
        conn.execute(
            """
            UPDATE documents
            SET security_id = ?, market = ?, exchange = ?, document_category = ?, document_subtype = ?, title = ?, source_platform = ?
            WHERE id = ?
            """,
            (
                dossier["security_id"],
                dossier["market"],
                dossier["exchange"],
                category,
                subtype,
                title,
                "sec" if dossier["market"] == "US" else "cninfo",
                row["id"],
            ),
        )

    for row in conn.execute("SELECT id, ticker, security_id, market, currency FROM advice_runs").fetchall():
        dossier = dossiers_by_ticker.get(row["ticker"])
        if not dossier:
            continue
        if row["security_id"] == dossier["security_id"] and row["market"] == dossier["market"] and row["currency"] == dossier["currency"]:
            continue
        conn.execute(
            "UPDATE advice_runs SET security_id = ?, market = ?, currency = ? WHERE id = ?",
            (dossier["security_id"], dossier["market"], dossier["currency"], row["id"]),
        )


def init_db() -> None:
    ensure_runtime_layout()
    with connect() as conn:
        conn.executescript(BASE_SCHEMA)
        _ensure_columns(conn)
        import_legacy_research(conn)
        _backfill_security_links(conn)
        ensure_unset_charter(conn)
        conn.commit()


def import_legacy_research(conn: sqlite3.Connection | None = None) -> None:
    owns_conn = conn is None
    if conn is None:
        conn = connect()
    now = utc_now_iso()
    try:
        for path in sorted(RESEARCH_DIR.iterdir()) if RESEARCH_DIR.exists() else []:
            if not path.is_dir():
                continue
            display_candidate = path.name.upper()
            ticker = normalize_symbol(display_candidate)
            row = conn.execute("SELECT ticker FROM dossiers WHERE ticker = ?", (ticker,)).fetchone()
            if row:
                continue
            company_name = ticker
            thesis = ""
            readme = path / "README.md"
            if readme.exists():
                excerpt = read_text_excerpt(readme, max_chars=500)
                lines = [line.strip("# ").strip() for line in excerpt.splitlines() if line.strip()]
                if lines:
                    company_name = lines[0][:120]
                    thesis = " ".join(lines[1:4])[:300]
            conn.execute(
                """
                INSERT INTO dossiers (ticker, company_name, status, thesis_summary, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?, ?)
                """,
                (ticker, company_name, thesis, now, now),
            )
    finally:
        if owns_conn:
            conn.commit()
            conn.close()


def ensure_unset_charter(conn: sqlite3.Connection | None = None) -> None:
    owns_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        row = conn.execute("SELECT version FROM charters LIMIT 1").fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO charters (status, raw_markdown, compiled_rules_json, active, created_at)
                VALUES ('unset', '', '{}', 0, ?)
                """,
                (utc_now_iso(),),
            )
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def next_charter_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM charters").fetchone()
    return int(row["version"]) + 1


def dossier_dir(display_code: str) -> Path:
    return RESEARCH_DIR / normalize_symbol(display_code).upper()
