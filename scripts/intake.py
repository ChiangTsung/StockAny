#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import CN_DISPLAY_CODE_RE, CN_SYMBOL_RE, US_SYMBOL_RE, normalize_symbol
from security_master import resolve_security_candidates


TICKER_PATTERN = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z])?)\b")
CN_CODE_PATTERN = re.compile(r"\b(\d{6}(?:\.(?:SH|SZ|BJ))?)\b", re.IGNORECASE)
PINYIN_PATTERN = re.compile(r"\b([a-z]{4,20})\b")
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")


def detect_charter_signal(message: str) -> dict[str, Any] | None:
    lowered = message.lower()
    signal_pairs = [
        ("sizing", ["仓位", "单票", "position", "allocate", "weight", "%"]),
        ("exit", ["止损", "卖出纪律", "thesis break", "exit", "卖掉"]),
        ("ban", ["不碰", "不买", "avoid", "never buy"]),
        ("add", ["加仓", "继续买", "add on weakness", "加码"]),
        ("trim", ["减仓", "止盈", "trim", "take profit"]),
        ("risk", ["风险", "drawdown", "回撤", "不确定性"]),
        ("style", ["成长", "价值", "event-driven", "长期", "短线"]),
        ("reflection", ["后悔", "复盘", "心得", "教训", "learned"]),
    ]
    for kind, keywords in signal_pairs:
        if any(keyword in lowered for keyword in keywords):
            return {
                "candidate_kind": kind,
                "candidate_text": message.strip(),
                "confidence": 0.72,
            }
    return None


def _extract_chinese_query(message: str) -> str:
    stop_words = {"今天", "我今天", "帮我", "跟踪", "研究", "同步", "一下", "最新公告", "最新财报", "买了", "卖了", "买入", "卖出", "股"}
    matches = [item for item in CHINESE_PATTERN.findall(message) if item not in stop_words]
    if not matches:
        return ""
    matches.sort(key=len, reverse=True)
    return matches[0]


def extract_security_query(message: str) -> str:
    code_match = CN_CODE_PATTERN.search(message)
    if code_match:
        return normalize_symbol(code_match.group(1))
    matches = TICKER_PATTERN.findall(message.upper())
    blacklist = {"USD", "CNY", "NYSE", "NASDAQ", "ETF"}
    for match in matches:
        if match not in blacklist:
            return normalize_symbol(match)
    chinese = _extract_chinese_query(message)
    if chinese:
        return chinese
    for word in PINYIN_PATTERN.findall(message.lower()):
        if word not in {"watch", "track", "today", "shares", "stockany"}:
            return word
    return ""


def parse_trade_message(message: str) -> dict[str, Any] | None:
    lowered = message.lower()
    side = None
    if any(keyword in lowered for keyword in ("买了", "买入", "买进", "加仓", "buy", "bought")):
        side = "buy"
    if any(keyword in lowered for keyword in ("卖了", "卖出", "减仓", "sell", "sold")):
        side = "sell"
    if not side:
        return None
    security_query = extract_security_query(message)
    if not security_query:
        return None
    quantity_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:股|shares?)", message, re.IGNORECASE)
    quantity = float(quantity_match.group(1)) if quantity_match else 1.0
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", message)]
    price = None
    if quantity_match:
        for number in numbers:
            if abs(number - quantity) > 1e-9:
                price = number
                break
    elif numbers:
        price = numbers[0]
    if price is None:
        at_match = re.search(r"(?:@|以|在|at)\s*(\d+(?:\.\d+)?)", message, re.IGNORECASE)
        if at_match:
            price = float(at_match.group(1))
    if price is None:
        return None
    return {
        "side": side,
        "quantity": quantity,
        "price": price,
        "security_query": security_query,
    }


def _security_matches(query: str) -> list[dict[str, Any]]:
    if not query:
        return []
    try:
        return resolve_security_candidates(query)
    except Exception:
        return []


def parse_message(message: str) -> dict[str, Any]:
    text = message.strip()
    lowered = text.lower()
    trade_match = parse_trade_message(text)

    if trade_match:
        matches = _security_matches(trade_match["security_query"])
        top = matches[0] if matches else {}
        return {
            "intent_type": "record_trade",
            "ticker": top.get("display_code") or trade_match["security_query"],
            "security_matches": matches,
            "trade": {
                "side": trade_match["side"],
                "quantity": trade_match["quantity"],
                "price": trade_match["price"],
            },
            "thesis_summary": "",
            "charter_signal": detect_charter_signal(text),
            "requested_action": "record_trade",
            "confidence": 0.9 if len(matches) == 1 else 0.72,
            "needs_confirmation": True,
        }

    if any(keyword in lowered for keyword in ("跟踪", "建档", "watch", "track", "研究")):
        security_query = extract_security_query(text)
        matches = _security_matches(security_query)
        top = matches[0] if matches else {}
        thesis = text
        for separator in ("逻辑是", "理由是", "because", " thesis ", " thesis:"):
            if separator in lowered:
                idx = lowered.find(separator)
                thesis = text[idx + len(separator) :].strip(" ：:")
                break
        return {
            "intent_type": "create_dossier",
            "ticker": top.get("display_code") or security_query,
            "security_matches": matches,
            "trade": None,
            "thesis_summary": thesis[:300],
            "charter_signal": detect_charter_signal(text),
            "requested_action": "create_dossier",
            "confidence": 0.9 if len(matches) == 1 else 0.6,
            "needs_confirmation": True,
        }

    if any(keyword in lowered for keyword in ("建议", "怎么看", "should i", "advice", "军师")):
        security_query = extract_security_query(text)
        matches = _security_matches(security_query)
        top = matches[0] if matches else {}
        return {
            "intent_type": "ask_advice",
            "ticker": top.get("display_code") or security_query,
            "security_matches": matches,
            "trade": None,
            "thesis_summary": "",
            "charter_signal": detect_charter_signal(text),
            "requested_action": "generate_advice",
            "confidence": 0.8 if matches else 0.55,
            "needs_confirmation": False,
        }

    if detect_charter_signal(text):
        security_query = extract_security_query(text)
        matches = _security_matches(security_query)
        top = matches[0] if matches else {}
        return {
            "intent_type": "add_note",
            "ticker": top.get("display_code") or security_query,
            "security_matches": matches,
            "trade": None,
            "thesis_summary": "",
            "charter_signal": detect_charter_signal(text),
            "requested_action": "capture_charter_signal",
            "confidence": 0.68,
            "needs_confirmation": False,
        }

    security_query = extract_security_query(text)
    matches = _security_matches(security_query)
    top = matches[0] if matches else {}
    return {
        "intent_type": "unknown",
        "ticker": top.get("display_code") or security_query,
        "security_matches": matches,
        "trade": None,
        "thesis_summary": "",
        "charter_signal": detect_charter_signal(text),
        "requested_action": "clarify",
        "confidence": 0.35,
        "needs_confirmation": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["parse-message"])
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    print(json.dumps(parse_message(args.message), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
