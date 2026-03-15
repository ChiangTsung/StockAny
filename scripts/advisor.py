#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import sha256_text, utc_now_iso
from charter import load_charter_context
from db import connect, init_db
from market_data import quote_from_cache, refresh_market
from portfolio import portfolio_summary
from security_master import resolve_security_or_raise


PROMPT_VERSION = "stockany-agent-brief-v1.2"


def _recent_document_count(security_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM documents WHERE security_id = ? AND review_status = 'pending'",
            (security_id,),
        ).fetchone()
    return int(row["count"])


def _find_position(display_code: str) -> dict[str, Any] | None:
    summary = portfolio_summary()
    for group in summary["groups"]:
        for position in group["positions"]:
            if position["display_code"] == display_code:
                return position
    return None


def generate_advice_text(ticker: str, event_type: str) -> tuple[str, dict[str, Any]]:
    security = resolve_security_or_raise(ticker)
    position = _find_position(security["display_code"])
    refresh_market(security["display_code"])
    quote = quote_from_cache(security["display_code"]) or {}
    charter = load_charter_context()
    charter_status = charter["status"]
    compiled = charter["compiled_rules_json"]
    charter_full_markdown = charter.get("raw_markdown") or ""
    pending_docs = _recent_document_count(security["security_id"])
    conflicts = []
    if charter_status == "unset":
        conflicts.append("当前没有正式投资宪章，建议需要以更保守的方式解读。")
    if position and compiled.get("position_sizing_rules", []):
        conflicts.append("已有仓位规则，请结合完整投资宪章检查当前仓位是否符合你的预设框架。")
    if compiled.get("add_conditions", []) and event_type == "trade_changed":
        conflicts.append("这次仓位变动需要结合完整宪章里的加仓/减仓条件一起判断，不能只看单条规则。")
    evidence = [
        f"市场: {security['market']} / {security['exchange']} / {security['currency']}",
        f"最新价格: {quote.get('market_price')}",
        f"持仓: {position['quantity']} 股 @ {position['average_cost']}" if position else "当前无持仓或持仓尚未建账。",
        f"待审阅公告/财报数: {pending_docs}",
    ]
    if security["market"] == "CN":
        evidence.append("A股公告/财报来自巨潮或沪深京官方披露体系。")
    else:
        evidence.append("美股公告/财报来自 SEC。")
    action = "先确认 thesis 与最新公告/财报是否一致，再决定是否扩仓。"
    if event_type == "trade_changed":
        action = "复核这笔交易是否符合你的仓位纪律、市场环境和 thesis 证据。"
    elif event_type == "dossier_created":
        action = "先补充你对仓位上限、卖出纪律的偏好，后续建议会更贴近你的风格。"
    questions = ["你的单票仓位上限是多少？", "什么情况会触发你卖出或减仓？"]
    if charter_status != "unset":
        questions = ["这次动作是否仍然符合你的正式投资宪章？"]
    lines = [
        f"# Briefing for {security['display_code']}",
        "",
        "## Agent Task",
        "- 使用当前 agent 自身的大模型能力，基于以下证据和完整投资宪章给出最终建议。",
        "- 不要只依赖编译后的局部规则；必须把完整宪章正文作为一等上下文。",
        "",
        "## 主要依据",
    ]
    lines.extend(f"- {item}" for item in evidence)
    lines.extend(
        [
            "",
            "## 宪章读取要求",
            f"- charter_status: {charter_status}",
            f"- charter_source_file: {charter['source_file']}",
            f"- charter_versioned_source_file: {charter.get('versioned_source_file', '')}",
            f"- charter_version: {charter.get('version', 0)}",
        ]
    )
    lines.extend(["", "## 与当前宪章或候选规则的关系"])
    if conflicts:
        lines.extend(f"- {item}" for item in conflicts)
    else:
        lines.append("- 当前没有明显冲突。")
    if charter_full_markdown:
        lines.extend(["", "## 完整投资宪章", charter_full_markdown.rstrip()])
    lines.extend(["", "## 建议动作候选", f"- {action}", "", "## 需要你确认的问题"])
    lines.extend(f"- {item}" for item in questions)
    text = "\n".join(lines)
    metadata = {
        "ticker": security["display_code"],
        "display_code": security["display_code"],
        "market": security["market"],
        "exchange": security["exchange"],
        "currency": security["currency"],
        "event_type": event_type,
        "briefing_mode": "agent-native",
        "suggested_stance": "cautious",
        "risk_level": "medium" if charter_status != "unset" else "elevated",
        "charter_status": charter_status,
        "charter_version": charter.get("version", 0),
        "charter_source_file": charter["source_file"],
        "charter_versioned_source_file": charter.get("versioned_source_file", ""),
        "charter_full_markdown": charter_full_markdown,
        "compiled_rules_json": compiled,
        "charter_conflicts": conflicts,
        "evidence_refs": evidence,
        "followup_questions": questions,
        "suggested_action": action,
    }
    return text, metadata


def generate_advice_run(ticker: str, event_type: str) -> dict[str, Any]:
    init_db()
    security = resolve_security_or_raise(ticker)
    text, metadata = generate_advice_text(security["display_code"], event_type)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO advice_runs (ticker, security_id, market, currency, event_type, inputs_hash, model_provider, model_name, prompt_version, output_markdown, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                security["display_code"],
                security["security_id"],
                security["market"],
                security["currency"],
                event_type,
                sha256_text(json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
                "agent-native",
                "external-model",
                PROMPT_VERSION,
                text,
                utc_now_iso(),
            ),
        )
        conn.commit()
    return {"markdown": text, "metadata": metadata}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--event-type", required=True)
    args = parser.parse_args()
    print(json.dumps(generate_advice_run(args.ticker, args.event_type), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
