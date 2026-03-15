#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from common import CACHE_DIR, cache_quote_name, dump_json, fetch_json, normalize_symbol, utc_now_iso
from db import connect, init_db
from security_master import resolve_security_or_raise, upsert_security

try:
    import akshare as ak
except Exception:  # pragma: no cover - runtime dependency
    ak = None


QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def _canonical_us_exchange(value: str) -> str:
    raw = (value or "").upper()
    if any(token in raw for token in ("NASDAQ", "NMS", "NCM", "NGM")):
        return "NASDAQ"
    if any(token in raw for token in ("NYSE", "NYQ")):
        return "NYSE"
    return raw


def _market_epoch_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def active_securities() -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT d.security_id, d.market, d.exchange, d.currency, d.display_code, s.symbol, s.company_name, s.company_name_zh
            FROM dossiers d
            JOIN securities s ON s.security_id = d.security_id
            WHERE d.status = 'active'
            ORDER BY d.display_code
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _cache_quote(payload: dict[str, Any]) -> dict[str, Any]:
    filename = cache_quote_name(payload["market"], payload["display_code"])
    dump_json(CACHE_DIR / filename, payload)
    return payload


def _refresh_security_metadata(security: dict[str, Any], *, exchange: str = "", company_name: str = "", currency: str = "") -> None:
    payload = dict(security)
    payload["exchange"] = _canonical_us_exchange(exchange) if security["market"] == "US" else (exchange or security.get("exchange", ""))
    payload["company_name"] = company_name or security.get("company_name", "") or security.get("display_code", "")
    payload["currency"] = currency or security.get("currency", "") or ("CNY" if security["market"] == "CN" else "USD")
    payload["updated_at"] = utc_now_iso()
    with connect() as conn:
        upsert_security(conn, payload)
        conn.execute(
            "UPDATE dossiers SET exchange = ?, currency = ?, updated_at = ? WHERE security_id = ?",
            (payload["exchange"], payload["currency"], utc_now_iso(), security["security_id"]),
        )
        conn.commit()


def _fetch_us_quote(security: dict[str, Any]) -> dict[str, Any]:
    ticker = security["symbol"]
    try:
        payload = fetch_json(CHART_URL.format(ticker=ticker), params={"interval": "1d", "range": "5d"})
        result = payload.get("chart", {}).get("result", [])
        if result:
            item = result[0]
            meta = item.get("meta", {})
            previous_close = meta.get("chartPreviousClose")
            market_price = meta.get("regularMarketPrice")
            market_change = None
            market_change_percent = None
            if market_price is not None and previous_close not in (None, 0):
                market_change = market_price - previous_close
                market_change_percent = market_change / previous_close * 100
            exchange = security["exchange"] or meta.get("exchangeName") or ""
            short_name = meta.get("shortName") or meta.get("symbol") or security["display_code"]
            currency = security["currency"] or meta.get("currency") or "USD"
            _refresh_security_metadata(security, exchange=exchange, company_name=short_name, currency=currency)
            return _cache_quote(
                {
                    "ticker": security["display_code"],
                    "market": "US",
                    "exchange": exchange,
                    "currency": currency,
                    "display_code": security["display_code"],
                    "short_name": short_name,
                    "market_price": market_price,
                    "market_change": market_change,
                    "market_change_percent": market_change_percent,
                    "market_time": meta.get("regularMarketTime"),
                    "fetched_at": utc_now_iso(),
                }
            )
    except Exception:
        pass

    payload = fetch_json(QUOTE_URL, params={"symbols": ticker})
    result = payload.get("quoteResponse", {}).get("result", [])
    if not result:
        raise RuntimeError(f"no quote returned for {ticker}")
    item = result[0]
    exchange = security["exchange"] or item.get("fullExchangeName") or item.get("exchange") or ""
    short_name = item.get("shortName") or item.get("longName") or security["display_code"]
    currency = security["currency"] or item.get("currency") or "USD"
    _refresh_security_metadata(security, exchange=exchange, company_name=short_name, currency=currency)
    return _cache_quote(
        {
            "ticker": security["display_code"],
            "market": "US",
            "exchange": exchange,
            "currency": currency,
            "display_code": security["display_code"],
            "short_name": short_name,
            "market_price": item.get("regularMarketPrice"),
            "market_change": item.get("regularMarketChange"),
            "market_change_percent": item.get("regularMarketChangePercent"),
            "market_time": item.get("regularMarketTime"),
            "fetched_at": utc_now_iso(),
        }
    )


def _fetch_cn_quote(security: dict[str, Any]) -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("AKShare is required for A-share market data. Install with: python3 -m pip install --user akshare pypinyin")
    quote_df = ak.stock_bid_ask_em(symbol=security["symbol"])
    quote_map = dict(zip(quote_df["item"], quote_df["value"]))
    info_df = ak.stock_individual_info_em(symbol=security["symbol"])
    info_map = dict(zip(info_df["item"], info_df["value"]))
    latest = quote_map.get("最新")
    previous_close = quote_map.get("昨收")
    market_change = quote_map.get("涨跌")
    market_change_percent = quote_map.get("涨幅")
    if market_change_percent is not None:
        market_change_percent = float(market_change_percent)
    if market_change is None and latest is not None and previous_close not in (None, 0):
        market_change = float(latest) - float(previous_close)
    payload = {
        "ticker": security["display_code"],
        "market": "CN",
        "exchange": security["exchange"],
        "currency": "CNY",
        "display_code": security["display_code"],
        "short_name": security.get("company_name_zh") or security.get("company_name") or info_map.get("股票简称") or security["display_code"],
        "market_price": latest,
        "market_change": market_change,
        "market_change_percent": market_change_percent,
        "market_time": _market_epoch_now(),
        "fetched_at": utc_now_iso(),
        "financial_metrics": {
            "total_market_cap": info_map.get("总市值"),
            "circulating_market_cap": info_map.get("流通市值"),
            "industry": info_map.get("行业"),
            "listing_date": info_map.get("上市时间"),
        },
    }
    _refresh_security_metadata(security, exchange=security["exchange"], company_name=payload["short_name"], currency="CNY")
    return _cache_quote(payload)


def fetch_quote_for_security(security: dict[str, Any]) -> dict[str, Any]:
    if security["market"] == "CN":
        return _fetch_cn_quote(security)
    return _fetch_us_quote(security)


def refresh_market(target: str) -> Any:
    if target == "all-active":
        securities = active_securities()
    else:
        securities = [resolve_security_or_raise(target)]
    results = []
    errors = []
    for security in securities:
        try:
            results.append(fetch_quote_for_security(security))
        except Exception as exc:
            errors.append({"ticker": security["display_code"], "market": security["market"], "error": str(exc)})
    return {"quotes": results, "errors": errors}


def quote_from_cache(ticker: str) -> dict[str, Any] | None:
    security = resolve_security_or_raise(ticker)
    candidates = [
        CACHE_DIR / cache_quote_name(security["market"], security["display_code"]),
        CACHE_DIR / f"quote-{normalize_symbol(ticker)}.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    print(json.dumps(refresh_market(args.ticker), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
