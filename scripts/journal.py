#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from charter import add_candidate
from common import JOURNAL_DIR, REPORTS_DIR, dump_json, sha256_text, today_str, utc_now_iso
from db import connect, init_db
from intake import detect_charter_signal
from portfolio import portfolio_summary


def journal_path_for(date_str: str) -> Path:
    return JOURNAL_DIR / f"{date_str}.jsonl"


def append_journal_entry(message: str, source: str = "chat", date_str: str | None = None) -> dict[str, Any]:
    init_db()
    target_date = date_str or today_str()
    path = journal_path_for(target_date)
    payload = {"timestamp": utc_now_iso(), "source": source, "message": message}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def _read_journal_entries(path: Path | None, review_date: str) -> list[dict[str, Any]]:
    journal_file = path or journal_path_for(review_date)
    if not journal_file.exists():
        return []
    entries = []
    with journal_file.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def _collect_document_alerts() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ticker, market, exchange, title, document_subtype, filed_at, source_platform
            FROM documents
            WHERE review_status = 'pending'
            ORDER BY filed_at DESC, id DESC
            LIMIT 30
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _collect_position_alerts() -> list[dict[str, Any]]:
    summary = portfolio_summary()
    alerts = []
    for group in summary["groups"]:
        for position in group["positions"]:
            alerts.append(
                {
                    "market": group["market"],
                    "currency": group["currency"],
                    "exchange": position["exchange"],
                    "ticker": position["display_code"],
                    "message": f"{position['display_code']} {position['quantity']} shares at avg cost {position['average_cost']}",
                }
            )
    return alerts


def run_daily_review(review_date: str | None = None, journal_path: str | None = None) -> dict[str, Any]:
    init_db()
    date_str = review_date or today_str()
    entries = _read_journal_entries(Path(journal_path) if journal_path else None, date_str)
    new_candidates = []
    for idx, entry in enumerate(entries):
        signal = detect_charter_signal(entry.get("message", ""))
        if not signal:
            continue
        candidate_id = add_candidate(
            source_type=entry.get("source", "chat"),
            source_ref=f"{date_str}:{idx}",
            candidate_text=signal["candidate_text"],
            candidate_kind=signal["candidate_kind"],
            confidence=float(signal["confidence"]),
        )
        new_candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_kind": signal["candidate_kind"],
                "candidate_text": signal["candidate_text"],
                "confidence": signal["confidence"],
            }
        )
    document_alerts = _collect_document_alerts()
    position_alerts = _collect_position_alerts()
    open_questions = [
        "哪些候选规则要正式并入投资宪章？",
        "今天的交易是否暴露了新的仓位纪律或退出纪律？",
    ]
    groups = {}
    for candidate in new_candidates:
        groups.setdefault(candidate["candidate_kind"], []).append(candidate["candidate_text"])
    report = [
        f"# Daily Charter Review - {date_str}",
        "",
        "## 今日新增的宪章候选",
    ]
    if new_candidates:
        report.extend(f"- [{item['candidate_kind']}] {item['candidate_text']}" for item in new_candidates)
    else:
        report.append("- 今天没有提炼出新的宪章候选。")
    report.extend(
        [
            "",
            "## 为什么系统认为这些值得写进宪章",
            "- 这些表达直接涉及仓位、风格、风险、退出纪律或复盘反思，会改变未来建议的个性化程度。",
            "",
            "## 待你确认的候选条目",
        ]
    )
    if new_candidates:
        report.extend(f"- Candidate #{item['candidate_id']}: {item['candidate_text']}" for item in new_candidates)
    else:
        report.append("- 暂无待确认候选。")
    report.extend(["", "## 财报/持仓提醒"])
    if document_alerts:
        for item in document_alerts:
            report.append(
                f"- [{item['market']}] {item['ticker']} {item['document_subtype']} {item['filed_at']} via {item['source_platform']}: {item['title']}"
            )
    else:
        report.append("- 没有新的待审阅财报。")
    if position_alerts:
        for item in position_alerts:
            report.append(f"- [{item['market']}/{item['currency']}] {item['message']}")
    report.extend(["", "## 明日需要关注的点"])
    report.extend(f"- {question}" for question in open_questions)
    report_path = REPORTS_DIR / f"daily-review-{date_str}.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    payload = {
        "review_date": date_str,
        "new_charter_candidates": new_candidates,
        "candidate_groups": groups,
        "document_alerts": document_alerts,
        "position_alerts": position_alerts,
        "open_questions": open_questions,
    }
    dump_json(report_path.with_suffix(".json"), payload)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO daily_reviews (review_date, summary_path, inputs_hash, candidate_count, document_alert_count, position_alert_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_date) DO UPDATE SET
                summary_path = excluded.summary_path,
                inputs_hash = excluded.inputs_hash,
                candidate_count = excluded.candidate_count,
                document_alert_count = excluded.document_alert_count,
                position_alert_count = excluded.position_alert_count,
                created_at = excluded.created_at
            """,
            (
                date_str,
                str(report_path),
                sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                len(new_candidates),
                len(document_alerts),
                len(position_alerts),
                utc_now_iso(),
            ),
        )
        conn.commit()
    return {"report_path": str(report_path), **payload}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["append", "daily"])
    parser.add_argument("--message")
    parser.add_argument("--source", default="chat")
    parser.add_argument("--review-date")
    parser.add_argument("--journal-path")
    args = parser.parse_args()
    if args.command == "append":
        if not args.message:
            raise SystemExit("--message is required for append")
        print(json.dumps(append_journal_entry(args.message, source=args.source), ensure_ascii=False, indent=2))
        return
    print(json.dumps(run_daily_review(review_date=args.review_date, journal_path=args.journal_path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
