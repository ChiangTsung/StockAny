#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import REPORTS_DIR, bootstrap_path, dump_json, ensure_runtime_layout

bootstrap_path()

from advisor import generate_advice_run
from charter import (
    list_charter_history,
    list_candidates,
    merge_candidates,
    review_candidate,
    set_charter_from_file,
    show_charter,
    switch_charter_version,
)
from db import connect, dossier_dir, init_db
from evaluation import list_evaluation_history, rebuild_evaluation, show_evaluation, switch_evaluation_version
from filings import review_documents, sync_filings
from intake import parse_message
from journal import run_daily_review
from market_data import refresh_market
from portfolio import portfolio_summary, record_trade
from security_master import resolve_security, resolve_security_candidates, resolve_security_or_raise
from topic_runtime import archive_topic, commit_turn, open_topic, prepare_turn, show_topic


def _pick_security_from_args(args: argparse.Namespace) -> tuple[dict | None, dict | None]:
    security_query = getattr(args, "query", None) or getattr(args, "symbol", None) or getattr(args, "ticker", None)
    if not security_query:
        raise SystemExit("one of --ticker, --symbol, or --query is required")
    matches = resolve_security_candidates(security_query, market=getattr(args, "market", None))
    if not matches:
        raise SystemExit(json.dumps({"error": "security_not_found", "query": security_query}, ensure_ascii=False))
    if len(matches) > 1 and matches[0]["confidence"] < 0.99:
        return None, {"query": security_query, "matches": matches[:10]}
    return matches[0], None


def cmd_security_resolve(args: argparse.Namespace) -> None:
    print(json.dumps(resolve_security(args.query, market=args.market), ensure_ascii=False, indent=2))


def cmd_dossier_create(args: argparse.Namespace) -> None:
    security, ambiguous = _pick_security_from_args(args)
    if ambiguous:
        print(json.dumps({"created": False, **ambiguous}, ensure_ascii=False, indent=2))
        return
    init_db()
    ensure_runtime_layout()
    with connect() as conn:
        now = __import__("common").utc_now_iso()
        conn.execute(
            """
            INSERT INTO dossiers (ticker, security_id, market, exchange, currency, display_code, company_name, status, thesis_summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, ?), 'active', ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                security_id = excluded.security_id,
                market = excluded.market,
                exchange = excluded.exchange,
                currency = excluded.currency,
                display_code = excluded.display_code,
                company_name = COALESCE(excluded.company_name, dossiers.company_name),
                thesis_summary = excluded.thesis_summary,
                updated_at = excluded.updated_at
            """,
            (
                security["display_code"],
                security["security_id"],
                security["market"],
                security["exchange"],
                security["currency"],
                security["display_code"],
                args.company_name,
                security.get("company_name_zh") or security.get("company_name") or security["display_code"],
                args.thesis or "",
                now,
                now,
            ),
        )
        conn.commit()
    base = dossier_dir(security["display_code"])
    for folder in ("notes", "sources", "analysis"):
        (base / folder).mkdir(parents=True, exist_ok=True)
    refresh = refresh_market(security["display_code"])
    payload = {"created": True, "ticker": security["display_code"], "market": refresh}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_dossier_list(_: argparse.Namespace) -> None:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ticker, display_code, market, exchange, currency, company_name, status, thesis_summary, updated_at
            FROM dossiers
            ORDER BY market, display_code
            """
        ).fetchall()
    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))


def cmd_dossier_show(args: argparse.Namespace) -> None:
    security = resolve_security_or_raise(args.ticker)
    init_db()
    with connect() as conn:
        dossier = conn.execute("SELECT * FROM dossiers WHERE security_id = ?", (security["security_id"],)).fetchone()
        trades = conn.execute(
            """
            SELECT side, quantity, price, traded_at, note, market, currency
            FROM trade_events
            WHERE security_id = ?
            ORDER BY traded_at DESC LIMIT 10
            """,
            (security["security_id"],),
        ).fetchall()
        docs = conn.execute(
            """
            SELECT title, document_category, document_subtype, period_end, filed_at, review_status, local_path, market, exchange, source_platform
            FROM documents
            WHERE security_id = ?
            ORDER BY filed_at DESC LIMIT 10
            """,
            (security["security_id"],),
        ).fetchall()
        advice = conn.execute(
            """
            SELECT event_type, model_provider, model_name, created_at, market, currency
            FROM advice_runs
            WHERE security_id = ?
            ORDER BY created_at DESC LIMIT 5
            """,
            (security["security_id"],),
        ).fetchall()
    if not dossier:
        raise SystemExit(f"dossier not found for {security['display_code']}")
    payload = dict(dossier)
    payload["recent_trades"] = [dict(row) for row in trades]
    payload["documents"] = [dict(row) for row in docs]
    payload["advice_runs"] = [dict(row) for row in advice]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_portfolio_record_trade(args: argparse.Namespace) -> None:
    security, ambiguous = _pick_security_from_args(args)
    if ambiguous:
        print(json.dumps({"recorded": False, **ambiguous}, ensure_ascii=False, indent=2))
        return
    result = record_trade(
        ticker=security["display_code"],
        side=args.side,
        quantity=args.quantity,
        price=args.price,
        traded_at=args.traded_at,
        fees=args.fees,
        note=args.note,
        source_message=args.source_message,
        market=security["market"],
        symbol=security["symbol"],
        currency=args.currency,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_portfolio_summary(_: argparse.Namespace) -> None:
    print(json.dumps(portfolio_summary(), ensure_ascii=False, indent=2))


def cmd_market_refresh(args: argparse.Namespace) -> None:
    target = "all-active" if args.all_active else args.ticker
    print(json.dumps(refresh_market(target), ensure_ascii=False, indent=2))


def cmd_filings_sync(args: argparse.Namespace) -> None:
    target = "all-active" if args.all_active else args.ticker
    print(json.dumps(sync_filings(target), ensure_ascii=False, indent=2))


def cmd_filings_review(args: argparse.Namespace) -> None:
    print(json.dumps(review_documents(args.ticker), ensure_ascii=False, indent=2))


def cmd_advice_run(args: argparse.Namespace) -> None:
    result = generate_advice_run(args.ticker, args.event_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_charter_show(_: argparse.Namespace) -> None:
    print(json.dumps(show_charter(), ensure_ascii=False, indent=2))


def cmd_charter_set(args: argparse.Namespace) -> None:
    result = set_charter_from_file(Path(args.file))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_charter_history(_: argparse.Namespace) -> None:
    print(json.dumps(list_charter_history(), ensure_ascii=False, indent=2))


def cmd_charter_switch(args: argparse.Namespace) -> None:
    print(json.dumps(switch_charter_version(args.version), ensure_ascii=False, indent=2))


def cmd_charter_candidates_list(_: argparse.Namespace) -> None:
    print(json.dumps(list_candidates(), ensure_ascii=False, indent=2))


def cmd_charter_candidates_review(args: argparse.Namespace) -> None:
    print(json.dumps(review_candidate(args.candidate_id), ensure_ascii=False, indent=2))


def cmd_charter_candidates_merge(args: argparse.Namespace) -> None:
    print(json.dumps(merge_candidates(args.candidate_ids), ensure_ascii=False, indent=2))


def cmd_review_daily(args: argparse.Namespace) -> None:
    result = run_daily_review(review_date=args.review_date, journal_path=args.journal_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_evaluation_show(_: argparse.Namespace) -> None:
    print(json.dumps(show_evaluation(), ensure_ascii=False, indent=2))


def cmd_evaluation_history(_: argparse.Namespace) -> None:
    print(json.dumps(list_evaluation_history(), ensure_ascii=False, indent=2))


def cmd_evaluation_switch(args: argparse.Namespace) -> None:
    print(json.dumps(switch_evaluation_version(args.version), ensure_ascii=False, indent=2))


def cmd_evaluation_rebuild(_: argparse.Namespace) -> None:
    print(json.dumps(rebuild_evaluation(), ensure_ascii=False, indent=2))


def cmd_snapshot_export(args: argparse.Namespace) -> None:
    security = resolve_security_or_raise(args.ticker)
    init_db()
    with connect() as conn:
        dossier = conn.execute("SELECT * FROM dossiers WHERE security_id = ?", (security["security_id"],)).fetchone()
        docs = conn.execute(
            """
            SELECT title, filed_at, local_path
            FROM documents
            WHERE security_id = ?
            ORDER BY filed_at DESC LIMIT 5
            """,
            (security["security_id"],),
        ).fetchall()
    position = None
    for group in portfolio_summary().get("groups", []):
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
        "- Recent documents:",
    ]
    for doc in docs:
        lines.append(f"  - {doc['title']} {doc['filed_at']} -> {doc['local_path']}")
    out_path = REPORTS_DIR / f"{security['display_code'].lower()}-snapshot.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dump_json(out_path.with_suffix(".json"), {"ticker": security["display_code"], "path": str(out_path)})
    print(json.dumps({"ticker": security["display_code"], "snapshot_path": str(out_path)}, ensure_ascii=False, indent=2))


def cmd_topic_open(args: argparse.Namespace) -> None:
    print(json.dumps(open_topic(args.query), ensure_ascii=False, indent=2))


def cmd_topic_show(args: argparse.Namespace) -> None:
    print(json.dumps(show_topic(args.topic_id), ensure_ascii=False, indent=2))


def cmd_topic_archive(args: argparse.Namespace) -> None:
    print(json.dumps(archive_topic(args.topic_id), ensure_ascii=False, indent=2))


def cmd_topic_turn_prepare(args: argparse.Namespace) -> None:
    result = prepare_turn(topic_id=args.topic_id, topic_query=args.topic_query, message=args.message or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_topic_turn_commit(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.commit_json).read_text(encoding="utf-8"))
    print(json.dumps(commit_turn(args.topic_id, payload), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stockany")
    sub = parser.add_subparsers(dest="command", required=True)

    security = sub.add_parser("security")
    security_sub = security.add_subparsers(dest="security_command", required=True)
    security_resolve = security_sub.add_parser("resolve")
    security_resolve.add_argument("--query", required=True)
    security_resolve.add_argument("--market")
    security_resolve.set_defaults(func=cmd_security_resolve)

    dossier = sub.add_parser("dossier")
    dossier_sub = dossier.add_subparsers(dest="dossier_command", required=True)
    dossier_create = dossier_sub.add_parser("create")
    dossier_target = dossier_create.add_mutually_exclusive_group(required=True)
    dossier_target.add_argument("--ticker")
    dossier_target.add_argument("--symbol")
    dossier_target.add_argument("--query")
    dossier_create.add_argument("--market")
    dossier_create.add_argument("--company-name")
    dossier_create.add_argument("--thesis", default="")
    dossier_create.set_defaults(func=cmd_dossier_create)
    dossier_list = dossier_sub.add_parser("list")
    dossier_list.set_defaults(func=cmd_dossier_list)
    dossier_show = dossier_sub.add_parser("show")
    dossier_show.add_argument("--ticker", required=True)
    dossier_show.set_defaults(func=cmd_dossier_show)

    portfolio = sub.add_parser("portfolio")
    portfolio_sub = portfolio.add_subparsers(dest="portfolio_command", required=True)
    portfolio_trade = portfolio_sub.add_parser("record-trade")
    portfolio_target = portfolio_trade.add_mutually_exclusive_group(required=True)
    portfolio_target.add_argument("--ticker")
    portfolio_target.add_argument("--symbol")
    portfolio_target.add_argument("--query")
    portfolio_trade.add_argument("--market")
    portfolio_trade.add_argument("--currency")
    portfolio_trade.add_argument("--side", required=True, choices=["buy", "sell"])
    portfolio_trade.add_argument("--quantity", required=True, type=float)
    portfolio_trade.add_argument("--price", required=True, type=float)
    portfolio_trade.add_argument("--traded-at", required=True)
    portfolio_trade.add_argument("--fees", type=float, default=0.0)
    portfolio_trade.add_argument("--note", default="")
    portfolio_trade.add_argument("--source-message", default="")
    portfolio_trade.set_defaults(func=cmd_portfolio_record_trade)
    portfolio_sum = portfolio_sub.add_parser("summary")
    portfolio_sum.set_defaults(func=cmd_portfolio_summary)

    market = sub.add_parser("market")
    market_sub = market.add_subparsers(dest="market_command", required=True)
    market_refresh = market_sub.add_parser("refresh")
    market_group = market_refresh.add_mutually_exclusive_group(required=True)
    market_group.add_argument("--ticker")
    market_group.add_argument("--all-active", action="store_true")
    market_refresh.set_defaults(func=cmd_market_refresh)

    filings = sub.add_parser("filings")
    filings_sub = filings.add_subparsers(dest="filings_command", required=True)
    filings_sync = filings_sub.add_parser("sync")
    filings_group = filings_sync.add_mutually_exclusive_group(required=True)
    filings_group.add_argument("--ticker")
    filings_group.add_argument("--all-active", action="store_true")
    filings_sync.set_defaults(func=cmd_filings_sync)
    filings_review = filings_sub.add_parser("review")
    filings_review.add_argument("--ticker", required=True)
    filings_review.set_defaults(func=cmd_filings_review)

    advice = sub.add_parser("advice")
    advice_sub = advice.add_subparsers(dest="advice_command", required=True)
    advice_run = advice_sub.add_parser("run")
    advice_run.add_argument("--ticker", required=True)
    advice_run.add_argument("--event-type", required=True, choices=["dossier_created", "trade_changed", "daily_review"])
    advice_run.set_defaults(func=cmd_advice_run)

    charter = sub.add_parser("charter")
    charter_sub = charter.add_subparsers(dest="charter_command", required=True)
    charter_show = charter_sub.add_parser("show")
    charter_show.set_defaults(func=cmd_charter_show)
    charter_history = charter_sub.add_parser("history")
    charter_history.set_defaults(func=cmd_charter_history)
    charter_switch = charter_sub.add_parser("switch")
    charter_switch.add_argument("--version", required=True, type=int)
    charter_switch.set_defaults(func=cmd_charter_switch)
    charter_set = charter_sub.add_parser("set")
    charter_set.add_argument("--file", required=True)
    charter_set.set_defaults(func=cmd_charter_set)
    charter_candidates = charter_sub.add_parser("candidates")
    candidate_sub = charter_candidates.add_subparsers(dest="candidate_command", required=True)
    candidate_list = candidate_sub.add_parser("list")
    candidate_list.set_defaults(func=cmd_charter_candidates_list)
    candidate_review = candidate_sub.add_parser("review")
    candidate_review.add_argument("--candidate-id", required=True, type=int)
    candidate_review.set_defaults(func=cmd_charter_candidates_review)
    candidate_merge = candidate_sub.add_parser("merge")
    candidate_merge.add_argument("--candidate-ids", nargs="+", type=int, required=True)
    candidate_merge.set_defaults(func=cmd_charter_candidates_merge)

    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_daily = review_sub.add_parser("daily")
    review_daily.add_argument("--review-date")
    review_daily.add_argument("--journal-path")
    review_daily.set_defaults(func=cmd_review_daily)

    snapshot = sub.add_parser("snapshot")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)
    snapshot_export = snapshot_sub.add_parser("export")
    snapshot_export.add_argument("--ticker", required=True)
    snapshot_export.set_defaults(func=cmd_snapshot_export)

    intake = sub.add_parser("intake")
    intake_sub = intake.add_subparsers(dest="intake_command", required=True)
    intake_parse = intake_sub.add_parser("parse-message")
    intake_parse.add_argument("--message", required=True)
    intake_parse.set_defaults(func=lambda args: print(json.dumps(parse_message(args.message), ensure_ascii=False, indent=2)))

    evaluation = sub.add_parser("evaluation")
    evaluation_sub = evaluation.add_subparsers(dest="evaluation_command", required=True)
    evaluation_show = evaluation_sub.add_parser("show")
    evaluation_show.set_defaults(func=cmd_evaluation_show)
    evaluation_history = evaluation_sub.add_parser("history")
    evaluation_history.set_defaults(func=cmd_evaluation_history)
    evaluation_switch = evaluation_sub.add_parser("switch")
    evaluation_switch.add_argument("--version", required=True, type=int)
    evaluation_switch.set_defaults(func=cmd_evaluation_switch)
    evaluation_rebuild = evaluation_sub.add_parser("rebuild")
    evaluation_rebuild.set_defaults(func=cmd_evaluation_rebuild)

    topic = sub.add_parser("topic")
    topic_sub = topic.add_subparsers(dest="topic_command", required=True)
    topic_open = topic_sub.add_parser("open")
    topic_open.add_argument("--query", required=True)
    topic_open.set_defaults(func=cmd_topic_open)
    topic_show = topic_sub.add_parser("show")
    topic_show.add_argument("--topic-id", required=True)
    topic_show.set_defaults(func=cmd_topic_show)
    topic_archive = topic_sub.add_parser("archive")
    topic_archive.add_argument("--topic-id", required=True)
    topic_archive.set_defaults(func=cmd_topic_archive)
    topic_turn = topic_sub.add_parser("turn")
    topic_turn_sub = topic_turn.add_subparsers(dest="topic_turn_command", required=True)
    topic_prepare = topic_turn_sub.add_parser("prepare")
    topic_prepare.add_argument("--topic-id")
    topic_prepare.add_argument("--topic-query")
    topic_prepare.add_argument("--message")
    topic_prepare.set_defaults(func=cmd_topic_turn_prepare)
    topic_commit = topic_turn_sub.add_parser("commit")
    topic_commit.add_argument("--topic-id", required=True)
    topic_commit.add_argument("--commit-json", required=True)
    topic_commit.set_defaults(func=cmd_topic_turn_commit)

    return parser


def main() -> None:
    init_db()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
