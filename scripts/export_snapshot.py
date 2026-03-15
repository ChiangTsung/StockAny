#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from common import REPORTS_DIR
from db import connect, init_db
from portfolio import portfolio_summary
from security_master import resolve_security_or_raise


def export_snapshot(ticker: str) -> dict[str, str]:
    init_db()
    security = resolve_security_or_raise(ticker)
    with connect() as conn:
        dossier = conn.execute(
            "SELECT thesis_summary, market, exchange, currency, display_code FROM dossiers WHERE security_id = ?",
            (security["security_id"],),
        ).fetchone()
        advice = conn.execute(
            "SELECT output_markdown FROM advice_runs WHERE security_id = ? ORDER BY created_at DESC LIMIT 1",
            (security["security_id"],),
        ).fetchone()
    position = None
    for group in portfolio_summary()["groups"]:
        for item in group["positions"]:
            if item["display_code"] == security["display_code"]:
                position = item
                break
    lines = [
        f"# {security['display_code']} Snapshot",
        "",
        f"- Market: {security['market']} / {security['exchange']} / {security['currency']}",
        f"- Thesis: {dossier['thesis_summary'] if dossier else ''}",
        f"- Position: {json.dumps(position, ensure_ascii=False)}" if position else "- Position: none",
        "",
        "## Latest Advice",
        advice["output_markdown"] if advice else "No advice generated yet.",
    ]
    path = REPORTS_DIR / f"{security['display_code'].lower()}-snapshot.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"snapshot_path": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    print(json.dumps(export_snapshot(args.ticker), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
