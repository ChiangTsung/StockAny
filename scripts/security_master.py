#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from common import (
    CACHE_DIR,
    CN_DISPLAY_CODE_RE,
    CN_SYMBOL_RE,
    US_SYMBOL_RE,
    detect_market,
    display_code_to_symbol,
    dump_json,
    fetch_json,
    format_display_code,
    infer_cn_exchange,
    load_json,
    normalize_symbol,
    utc_now_iso,
)
from db import connect, init_db

try:
    import akshare as ak
except Exception:  # pragma: no cover - runtime dependency
    ak = None

try:
    from pypinyin import lazy_pinyin
except Exception:  # pragma: no cover - runtime dependency
    lazy_pinyin = None


CN_SECURITIES_CACHE = CACHE_DIR / "cn-securities.json"
CN_SECURITIES_MAX_AGE_SECONDS = 24 * 60 * 60
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _cache_fresh(path, max_age_seconds: int) -> bool:
    if not path.exists():
        return False
    age = _now_epoch() - int(path.stat().st_mtime)
    return age <= max_age_seconds


def _to_pinyin(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    if lazy_pinyin is None:
        ascii_text = "".join(ch for ch in text.lower() if ch.isascii() and ch.isalnum())
        return ascii_text, ascii_text
    syllables = lazy_pinyin(text)
    return "".join(syllables), "".join(item[0] for item in syllables if item)


def _security_payload(
    market: str,
    exchange: str,
    symbol: str,
    company_name: str = "",
    company_name_zh: str = "",
    currency: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    display_code = format_display_code(market, symbol, exchange)
    name_pinyin, name_pinyin_abbr = _to_pinyin(company_name_zh)
    return {
        "market": market.upper(),
        "exchange": exchange,
        "symbol": display_code_to_symbol(symbol) if market.upper() == "CN" else symbol.upper(),
        "display_code": display_code,
        "company_name": company_name or display_code,
        "company_name_zh": company_name_zh or "",
        "name_pinyin": name_pinyin,
        "name_pinyin_abbr": name_pinyin_abbr,
        "currency": currency or ("CNY" if market.upper() == "CN" else "USD"),
        "status": "active",
        "source": source,
        "updated_at": utc_now_iso(),
    }


def upsert_security(conn, payload: dict[str, Any]) -> int:
    row = conn.execute(
        """
        INSERT INTO securities
        (market, exchange, symbol, display_code, company_name, company_name_zh, name_pinyin, name_pinyin_abbr, currency, status, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market, symbol) DO UPDATE SET
            exchange = excluded.exchange,
            display_code = excluded.display_code,
            company_name = CASE WHEN excluded.company_name != '' THEN excluded.company_name ELSE securities.company_name END,
            company_name_zh = CASE WHEN excluded.company_name_zh != '' THEN excluded.company_name_zh ELSE securities.company_name_zh END,
            name_pinyin = CASE WHEN excluded.name_pinyin != '' THEN excluded.name_pinyin ELSE securities.name_pinyin END,
            name_pinyin_abbr = CASE WHEN excluded.name_pinyin_abbr != '' THEN excluded.name_pinyin_abbr ELSE securities.name_pinyin_abbr END,
            currency = excluded.currency,
            status = excluded.status,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            payload["market"],
            payload["exchange"],
            payload["symbol"],
            payload["display_code"],
            payload["company_name"],
            payload["company_name_zh"],
            payload["name_pinyin"],
            payload["name_pinyin_abbr"],
            payload["currency"],
            payload["status"],
            payload["source"],
            payload.get("created_at", utc_now_iso()),
            payload["updated_at"],
        ),
    )
    row = conn.execute(
        "SELECT security_id FROM securities WHERE market = ? AND symbol = ?",
        (payload["market"], payload["symbol"]),
    ).fetchone()
    return int(row["security_id"])


def _canonical_us_exchange(value: str) -> str:
    raw = (value or "").upper()
    if any(token in raw for token in ("NASDAQ", "NMS", "NCM", "NGM")):
        return "NASDAQ"
    if any(token in raw for token in ("NYSE", "NYQ")):
        return "NYSE"
    return raw


def _lookup_us_metadata(symbol: str) -> dict[str, str]:
    try:
        payload = fetch_json(YAHOO_CHART_URL.format(ticker=symbol), params={"interval": "1d", "range": "5d"})
        rows = payload.get("chart", {}).get("result", [])
        if rows:
            meta = rows[0].get("meta", {})
            return {
                "company_name": meta.get("shortName") or meta.get("symbol") or symbol,
                "exchange": _canonical_us_exchange(meta.get("exchangeName") or ""),
                "currency": meta.get("currency") or "USD",
            }
    except Exception:
        pass
    try:
        payload = fetch_json(YAHOO_QUOTE_URL, params={"symbols": symbol})
        rows = payload.get("quoteResponse", {}).get("result", [])
        if not rows:
            return {}
        item = rows[0]
        return {
            "company_name": item.get("longName") or item.get("shortName") or symbol,
            "exchange": _canonical_us_exchange(item.get("fullExchangeName") or item.get("exchange") or ""),
            "currency": item.get("currency") or "USD",
        }
    except Exception:
        return {}


def ensure_us_security(symbol: str, company_name: str = "", exchange: str = "") -> dict[str, Any]:
    init_db()
    metadata = {}
    try:
        metadata = _lookup_us_metadata(symbol)
    except Exception:
        metadata = {}
    payload = _security_payload(
        "US",
        exchange or metadata.get("exchange", ""),
        symbol,
        company_name=company_name or metadata.get("company_name", ""),
        currency=metadata.get("currency", "USD"),
        source="legacy-us",
    )
    with connect() as conn:
        security_id = upsert_security(conn, payload)
        conn.commit()
        row = conn.execute("SELECT * FROM securities WHERE security_id = ?", (security_id,)).fetchone()
    return dict(row)


def _load_cn_rows_from_akshare() -> list[dict[str, Any]]:
    if ak is None:
        raise RuntimeError("AKShare is required for A-share support. Install with: python3 -m pip install --user akshare pypinyin")
    fetchers = [
        ("SSE", lambda: ak.stock_info_sh_name_code(symbol="主板A股"), "证券代码", "证券简称"),
        ("SSE", lambda: ak.stock_info_sh_name_code(symbol="科创板"), "证券代码", "证券简称"),
        ("SZSE", lambda: ak.stock_info_sz_name_code(symbol="A股列表"), "A股代码", "A股简称"),
        ("BSE", ak.stock_info_bj_name_code, "证券代码", "证券简称"),
    ]
    rows = []
    for exchange, fn, code_col, name_col in fetchers:
        df = fn()
        for item in df[[code_col, name_col]].drop_duplicates().to_dict(orient="records"):
            code = str(item[code_col]).strip()
            name = str(item[name_col]).replace(" ", "").strip()
            rows.append(
                _security_payload(
                    "CN",
                    exchange,
                    code,
                    company_name=name,
                    company_name_zh=name,
                    source="akshare",
                )
            )
    return rows


def refresh_cn_security_index(force: bool = False) -> dict[str, Any]:
    init_db()
    if not force and _cache_fresh(CN_SECURITIES_CACHE, CN_SECURITIES_MAX_AGE_SECONDS):
        payload = load_json(CN_SECURITIES_CACHE, default={"count": 0})
        if payload and payload.get("count", 0) > 0:
            return payload
    rows = _load_cn_rows_from_akshare()
    with connect() as conn:
        for row in rows:
            upsert_security(conn, row)
        conn.commit()
    payload = {"refreshed_at": utc_now_iso(), "count": len(rows)}
    dump_json(CN_SECURITIES_CACHE, payload)
    return payload


def _score_match(query: str, row: dict[str, Any]) -> float:
    query_lower = query.lower()
    symbol = (row.get("symbol") or "").lower()
    display_code = (row.get("display_code") or "").lower()
    company_name_zh = (row.get("company_name_zh") or "").lower()
    company_name = (row.get("company_name") or "").lower()
    name_pinyin = (row.get("name_pinyin") or "").lower()
    name_pinyin_abbr = (row.get("name_pinyin_abbr") or "").lower()
    if query_lower == display_code:
        return 1.0
    if query_lower == symbol:
        return 0.99
    if query_lower == company_name_zh:
        return 0.98
    if query_lower == company_name:
        return 0.97
    if query_lower == name_pinyin:
        return 0.96
    if query_lower == name_pinyin_abbr:
        return 0.95
    if query_lower in company_name_zh:
        return 0.85
    if query_lower in company_name:
        return 0.84
    if query_lower and query_lower in name_pinyin:
        return 0.83
    if query_lower and query_lower in name_pinyin_abbr:
        return 0.81
    return 0.0


def _rows_to_matches(query: str, rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    matches = []
    for row in rows:
        confidence = _score_match(query, row)
        if confidence <= 0:
            continue
        match = dict(row)
        match["confidence"] = round(confidence, 4)
        matches.append(match)
    matches.sort(key=lambda item: (-item["confidence"], item.get("display_code", "")))
    return matches[:limit]


def resolve_security_candidates(query: str, market: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    init_db()
    raw_query = query.strip()
    normalized = normalize_symbol(raw_query)
    preferred_market = (market or detect_market(raw_query) or "").upper()

    if preferred_market == "CN" or CN_SYMBOL_RE.match(normalized) or CN_DISPLAY_CODE_RE.match(normalized):
        refresh_cn_security_index(force=False)
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM securities WHERE market = 'CN' ORDER BY display_code"
            ).fetchall()
        matches = _rows_to_matches(display_code_to_symbol(normalized), [dict(row) for row in rows], limit=limit)
        if matches:
            return matches

    # For Chinese text and ascii words like pinyin abbreviations, search the CN index
    # before inventing a new US ticker.
    if any("\u4e00" <= ch <= "\u9fff" for ch in raw_query) or raw_query.isascii():
        refresh_cn_security_index(force=False)
        with connect() as conn:
            rows = conn.execute("SELECT * FROM securities WHERE market = 'CN' ORDER BY display_code").fetchall()
        cn_matches = _rows_to_matches(raw_query.strip().lower(), [dict(row) for row in rows], limit=limit)
        if cn_matches:
            return cn_matches

    with connect() as conn:
        exact_rows = conn.execute(
            """
            SELECT * FROM securities
            WHERE display_code = ? OR symbol = ? OR company_name = ? OR company_name_zh = ?
            ORDER BY display_code
            """,
            (normalized, normalized, raw_query, raw_query),
        ).fetchall()
    if exact_rows:
        if (
            len(exact_rows) == 1
            and exact_rows[0]["market"] == "US"
            and (not exact_rows[0]["exchange"] or exact_rows[0]["company_name"] == exact_rows[0]["symbol"])
        ):
            refreshed = ensure_us_security(exact_rows[0]["symbol"], company_name=exact_rows[0]["company_name"], exchange=exact_rows[0]["exchange"])
            return [{**refreshed, "confidence": _score_match(raw_query, refreshed) or 0.9}]
        return [{**dict(row), "confidence": _score_match(raw_query, dict(row)) or 0.9} for row in exact_rows[:limit]]

    if preferred_market == "US" or (
        raw_query.isascii()
        and raw_query.upper() == raw_query
        and US_SYMBOL_RE.match(normalized)
        and not CN_SYMBOL_RE.match(normalized)
    ):
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM securities WHERE market = 'US' AND (symbol = ? OR display_code = ?) LIMIT 1",
                (normalized, normalized),
            ).fetchone()
        if row:
            return [{**dict(row), "confidence": 1.0}]
        return [{**ensure_us_security(normalized), "confidence": 1.0}]

    return []


def resolve_security(query: str, market: str | None = None) -> dict[str, Any]:
    return {"query": query, "matches": resolve_security_candidates(query, market=market)}


def resolve_security_or_raise(query: str, market: str | None = None) -> dict[str, Any]:
    matches = resolve_security_candidates(query, market=market)
    if not matches:
        raise RuntimeError(f"security not found for query: {query}")
    if len(matches) > 1 and matches[0]["confidence"] < 0.99:
        raise RuntimeError(
            json.dumps(
                {"error": "ambiguous_security", "query": query, "matches": matches[:5]},
                ensure_ascii=False,
            )
        )
    return matches[0]
