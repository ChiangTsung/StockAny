#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any

from common import utc_now_iso
from db import connect, dossier_dir, init_db
from security_master import resolve_security_or_raise


def ensure_dossier_exists(conn, security: dict[str, Any], thesis_summary: str = "") -> None:
    row = conn.execute("SELECT ticker FROM dossiers WHERE security_id = ?", (security["security_id"],)).fetchone()
    if row:
        return
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO dossiers (ticker, security_id, market, exchange, currency, display_code, company_name, status, thesis_summary, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            security["display_code"],
            security["security_id"],
            security["market"],
            security["exchange"],
            security["currency"],
            security["display_code"],
            security.get("company_name_zh") or security.get("company_name") or security["display_code"],
            thesis_summary,
            now,
            now,
        ),
    )
    base = dossier_dir(security["display_code"])
    for folder in ("notes", "sources", "analysis"):
        (base / folder).mkdir(parents=True, exist_ok=True)


def _consume_sell_lots(conn, security: dict[str, Any], quantity: float) -> None:
    remaining = quantity
    rows = conn.execute(
        """
        SELECT id, remaining_quantity
        FROM position_lots
        WHERE security_id = ? AND remaining_quantity > 0
        ORDER BY opened_at, id
        """,
        (security["security_id"],),
    ).fetchall()
    total = sum(float(row["remaining_quantity"]) for row in rows)
    if total + 1e-9 < quantity:
        raise ValueError(f"not enough shares to sell {quantity} {security['display_code']}; current={total}")
    for row in rows:
        lot_qty = float(row["remaining_quantity"])
        take = min(remaining, lot_qty)
        left = lot_qty - take
        conn.execute("UPDATE position_lots SET remaining_quantity = ? WHERE id = ?", (left, row["id"]))
        remaining -= take
        if remaining <= 1e-9:
            break


def record_trade(
    ticker: str | None = None,
    side: str = "",
    quantity: float = 0.0,
    price: float = 0.0,
    traded_at: str = "",
    fees: float = 0.0,
    note: str = "",
    source_message: str = "",
    market: str | None = None,
    symbol: str | None = None,
    query: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    init_db()
    side = side.lower()
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if price <= 0:
        raise ValueError("price must be positive")
    security_query = query or symbol or ticker
    if not security_query:
        raise ValueError("one of ticker, symbol, or query is required")
    security = resolve_security_or_raise(security_query, market=market)
    with connect() as conn:
        ensure_dossier_exists(conn, security)
        conn.execute(
            """
            INSERT INTO trade_events (ticker, security_id, market, currency, side, quantity, price, traded_at, fees, note, source_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                security["display_code"],
                security["security_id"],
                security["market"],
                currency or security["currency"],
                side,
                quantity,
                price,
                traded_at,
                fees,
                note,
                source_message,
                utc_now_iso(),
            ),
        )
        if side == "buy":
            conn.execute(
                """
                INSERT INTO position_lots (ticker, security_id, market, currency, remaining_quantity, cost_basis, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    security["display_code"],
                    security["security_id"],
                    security["market"],
                    currency or security["currency"],
                    quantity,
                    price,
                    traded_at,
                ),
            )
        else:
            _consume_sell_lots(conn, security, quantity)
        conn.execute(
            "UPDATE dossiers SET updated_at = ? WHERE security_id = ?",
            (utc_now_iso(), security["security_id"]),
        )
        conn.commit()
    return {
        "ticker": security["display_code"],
        "market": security["market"],
        "currency": currency or security["currency"],
        "side": side,
        "quantity": quantity,
        "price": price,
        "traded_at": traded_at,
    }


def portfolio_summary() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                pl.market,
                pl.currency,
                s.exchange,
                s.display_code,
                COALESCE(s.company_name_zh, '') AS company_name_zh,
                COALESCE(s.company_name, '') AS company_name,
                ROUND(SUM(pl.remaining_quantity), 6) AS quantity,
                ROUND(SUM(pl.remaining_quantity * pl.cost_basis) / NULLIF(SUM(pl.remaining_quantity), 0), 6) AS average_cost
            FROM position_lots pl
            JOIN securities s ON s.security_id = pl.security_id
            WHERE pl.remaining_quantity > 0
            GROUP BY pl.market, pl.currency, s.exchange, s.display_code, s.company_name_zh, s.company_name
            ORDER BY pl.market, s.display_code
            """
        ).fetchall()
        trade_count = conn.execute("SELECT COUNT(*) AS count FROM trade_events").fetchone()
    groups_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        item["ticker"] = item["display_code"]
        item["short_name"] = item["company_name_zh"] or item["company_name"] or item["display_code"]
        key = (item["market"], item["currency"])
        groups_map.setdefault(key, []).append(item)
    groups = [
        {"market": market, "currency": currency, "positions": positions}
        for (market, currency), positions in groups_map.items()
    ]
    return {
        "groups": groups,
        "trade_count": int(trade_count["count"]),
    }


def main() -> None:
    print(json.dumps(portfolio_summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
