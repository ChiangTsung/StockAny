#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import ASSETS_DIR, EVALUATION_ACTIVE_PATH, EVALUATION_CACHE_PATH, EVALUATION_TEMPLATE_PATH, utc_now_iso
from db import connect, init_db


SECTION_MAP = {
    "security_focus_rules": "security_focus_rules",
    "metric_preferences": "metric_preferences",
    "sector_metric_preferences": "sector_metric_preferences",
    "report_preferences": "report_preferences",
}

DEFAULT_EVALUATION_MARKDOWN = """# StockAny Evaluation

## security_focus_rules
- 对高波动成长类标的，优先补充增长质量与预期差来源。

## metric_preferences
- 默认展示营收增速、利润率、现金流与估值框架。

## sector_metric_preferences
- 对制造、科技、医药等行业，优先补充分部收入、前瞻指标与经营质量。

## report_preferences
- 先给结论，再给证据与风险，最后列出待验证问题。
"""


def _versioned_evaluation_path(version: int) -> Path:
    return ASSETS_DIR / f"evaluation-v{version}.md"


def compile_evaluation_markdown(raw_markdown: str) -> dict[str, list[str]]:
    compiled = {key: [] for key in SECTION_MAP.values()}
    current = None
    for raw_line in raw_markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            heading = re.sub(r"[^a-z_]+", "_", line[3:].strip().lower()).strip("_")
            current = SECTION_MAP.get(heading)
            continue
        if line.startswith("- ") and current:
            compiled[current].append(line[2:].strip())
    return compiled


def render_evaluation_markdown(compiled: dict[str, list[str]]) -> str:
    lines = ["# StockAny Evaluation", ""]
    for section in SECTION_MAP.values():
        lines.append(f"## {section}")
        lines.extend(f"- {value}" for value in compiled.get(section, []))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def summarize_evaluation(compiled: dict[str, list[str]], limit: int = 4) -> str:
    items: list[str] = []
    for section in SECTION_MAP.values():
        items.extend(compiled.get(section, []))
        if len(items) >= limit:
            break
    return "；".join(items[:limit])


def _default_evaluation_markdown() -> str:
    if EVALUATION_TEMPLATE_PATH.exists():
        return EVALUATION_TEMPLATE_PATH.read_text(encoding="utf-8")
    return DEFAULT_EVALUATION_MARKDOWN


def _sync_evaluation_files(raw_markdown: str, version: int, compiled: dict[str, list[str]]) -> None:
    EVALUATION_ACTIVE_PATH.write_text(raw_markdown, encoding="utf-8")
    _versioned_evaluation_path(version).write_text(raw_markdown, encoding="utf-8")
    EVALUATION_CACHE_PATH.write_text(json.dumps(compiled, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_default_evaluation() -> None:
    init_db()
    raw_markdown = (
        EVALUATION_ACTIVE_PATH.read_text(encoding="utf-8")
        if EVALUATION_ACTIVE_PATH.exists()
        else _default_evaluation_markdown()
    )
    compiled = compile_evaluation_markdown(raw_markdown)
    with connect() as conn:
        row = conn.execute("SELECT version, raw_markdown, compiled_json FROM evaluation_versions WHERE active = 1 LIMIT 1").fetchone()
        if row:
            version = int(row["version"])
            active_raw = row["raw_markdown"] or ""
            active_compiled = json.loads(row["compiled_json"] or "{}")
            if active_raw != raw_markdown:
                _sync_evaluation_files(active_raw, version, active_compiled)
            else:
                _sync_evaluation_files(raw_markdown, version, compiled)
            return
        cursor = conn.execute(
            """
            INSERT INTO evaluation_versions (status, raw_markdown, compiled_json, source_type, source_ref, reason, active, created_at)
            VALUES ('active', ?, ?, 'system', '', 'initialize default evaluation', 1, ?)
            """,
            (raw_markdown, json.dumps(compiled, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
        version = int(cursor.lastrowid)
    _sync_evaluation_files(raw_markdown, version, compiled)


def _active_or_latest_evaluation(conn) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT version, status, raw_markdown, compiled_json, source_type, source_ref, reason, active, created_at
        FROM evaluation_versions
        WHERE active = 1
        ORDER BY version DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        row = conn.execute(
            """
            SELECT version, status, raw_markdown, compiled_json, source_type, source_ref, reason, active, created_at
            FROM evaluation_versions
            ORDER BY version DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else {}


def load_evaluation_context() -> dict[str, Any]:
    ensure_default_evaluation()
    with connect() as conn:
        row = _active_or_latest_evaluation(conn)
    if not row:
        compiled = compile_evaluation_markdown(_default_evaluation_markdown())
        return {
            "version": 0,
            "status": "active",
            "active": 1,
            "raw_markdown": _default_evaluation_markdown(),
            "compiled_json": compiled,
            "source_type": "system",
            "source_ref": "",
            "reason": "initialize default evaluation",
            "created_at": "",
            "source_file": str(EVALUATION_ACTIVE_PATH),
            "versioned_source_file": "",
            "summary": summarize_evaluation(compiled),
        }
    row["compiled_json"] = json.loads(row["compiled_json"] or "{}")
    version = int(row["version"])
    raw_markdown = row.get("raw_markdown") or ""
    versioned_path = _versioned_evaluation_path(version)
    active_text = EVALUATION_ACTIVE_PATH.read_text(encoding="utf-8") if EVALUATION_ACTIVE_PATH.exists() else ""
    versioned_text = versioned_path.read_text(encoding="utf-8") if versioned_path.exists() else ""
    if active_text != raw_markdown or versioned_text != raw_markdown:
        _sync_evaluation_files(raw_markdown, version, row["compiled_json"])
    row["source_file"] = str(EVALUATION_ACTIVE_PATH)
    row["versioned_source_file"] = str(versioned_path)
    row["summary"] = summarize_evaluation(row["compiled_json"])
    return row


def show_evaluation() -> dict[str, Any]:
    return load_evaluation_context()


def list_evaluation_history() -> dict[str, Any]:
    ensure_default_evaluation()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT version, status, active, source_type, source_ref, reason, created_at
            FROM evaluation_versions
            ORDER BY version DESC
            """
        ).fetchall()
    versions = []
    for row in rows:
        item = dict(row)
        item["versioned_source_file"] = str(_versioned_evaluation_path(int(item["version"])))
        versions.append(item)
    return {"versions": versions}


def _insert_evaluation_version(
    raw_markdown: str,
    *,
    source_type: str,
    source_ref: str,
    reason: str,
) -> dict[str, Any]:
    ensure_default_evaluation()
    compiled = compile_evaluation_markdown(raw_markdown)
    with connect() as conn:
        conn.execute("UPDATE evaluation_versions SET active = 0, status = 'superseded' WHERE active = 1")
        cursor = conn.execute(
            """
            INSERT INTO evaluation_versions (status, raw_markdown, compiled_json, source_type, source_ref, reason, active, created_at)
            VALUES ('active', ?, ?, ?, ?, ?, 1, ?)
            """,
            (raw_markdown, json.dumps(compiled, ensure_ascii=False), source_type, source_ref, reason, utc_now_iso()),
        )
        conn.commit()
        version = int(cursor.lastrowid)
    _sync_evaluation_files(raw_markdown, version, compiled)
    return {"version": version, "compiled": compiled}


def switch_evaluation_version(version: int) -> dict[str, Any]:
    ensure_default_evaluation()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT version, raw_markdown, compiled_json
            FROM evaluation_versions
            WHERE version = ?
            """,
            (version,),
        ).fetchone()
        if not row:
            raise ValueError(f"evaluation version {version} not found")
        conn.execute("UPDATE evaluation_versions SET active = 0, status = 'superseded' WHERE active = 1")
        conn.execute("UPDATE evaluation_versions SET active = 1, status = 'active' WHERE version = ?", (version,))
        conn.commit()
    _sync_evaluation_files(row["raw_markdown"], int(row["version"]), json.loads(row["compiled_json"] or "{}"))
    return show_evaluation()


def rebuild_evaluation() -> dict[str, Any]:
    ensure_default_evaluation()
    active = load_evaluation_context()
    raw_markdown = (
        EVALUATION_ACTIVE_PATH.read_text(encoding="utf-8")
        if EVALUATION_ACTIVE_PATH.exists()
        else active["raw_markdown"]
    )
    if raw_markdown == active["raw_markdown"]:
        compiled = compile_evaluation_markdown(raw_markdown)
        _sync_evaluation_files(raw_markdown, int(active["version"]), compiled)
        with connect() as conn:
            conn.execute(
                "UPDATE evaluation_versions SET compiled_json = ? WHERE version = ?",
                (json.dumps(compiled, ensure_ascii=False), active["version"]),
            )
            conn.commit()
        return show_evaluation()
    _insert_evaluation_version(
        raw_markdown,
        source_type="manual-file",
        source_ref=str(EVALUATION_ACTIVE_PATH),
        reason="rebuild from active evaluation file",
    )
    return show_evaluation()


def _normalize_signal(signal: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(signal, str):
        return {"signal_text": signal, "category": "metric_preferences", "explicit": True, "confidence": 0.8}
    return {
        "signal_text": (signal.get("signal_text") or signal.get("candidate_text") or "").strip(),
        "category": signal.get("category") or "metric_preferences",
        "explicit": bool(signal.get("explicit", False)),
        "confidence": float(signal.get("confidence", 0.75)),
    }


def detect_evaluation_signals(message: str) -> list[dict[str, Any]]:
    sentences = re.split(r"[。！？!?;\n]+", message)
    signals = []
    seen: set[tuple[str, str]] = set()
    for sentence in sentences:
        text = sentence.strip(" -:：")
        if not text:
            continue
        lowered = text.lower()
        if not any(keyword in text for keyword in ("关注", "重点", "展示", "额外", "默认", "查询", "补充")) and not any(
            keyword in lowered for keyword in ("focus", "highlight", "show", "default", "check")
        ):
            continue
        category = "metric_preferences"
        if any(keyword in text for keyword in ("报告", "结构", "展示", "写法")):
            category = "report_preferences"
        elif any(keyword in text for keyword in ("医药", "科技", "制造", "半导体", "消费", "金融", "地产", "行业", "成长类", "价值类")):
            category = "sector_metric_preferences"
        elif any(keyword in text for keyword in ("哪类标的", "对于", "优先看", "风格")):
            category = "security_focus_rules"
        signal = {
            "signal_text": text,
            "category": category,
            "explicit": any(keyword in text for keyword in ("默认", "需要", "必须", "以后", "优先", "习惯", "重点")),
            "confidence": 0.82,
        }
        key = (signal["category"], signal["signal_text"])
        if key in seen:
            continue
        seen.add(key)
        signals.append(signal)
    return signals


def _existing_signal_occurrences(signal_text: str) -> int:
    count = 0
    with connect() as conn:
        rows = conn.execute("SELECT evaluation_signals_json FROM topic_turns ORDER BY id DESC").fetchall()
    for row in rows:
        try:
            signals = json.loads(row["evaluation_signals_json"] or "[]")
        except json.JSONDecodeError:
            continue
        for signal in signals:
            text = (signal.get("signal_text") or signal.get("candidate_text") or "").strip()
            if text == signal_text:
                count += 1
    return count


def apply_evaluation_signals(signals: list[dict[str, Any] | str], source_ref: str = "") -> dict[str, Any]:
    if not signals:
        return {"updated": False, "version": 0, "applied": [], "pending": []}
    evaluation = load_evaluation_context()
    compiled = evaluation.get("compiled_json", {}) or {}
    for section in SECTION_MAP.values():
        compiled.setdefault(section, [])
    applied = []
    pending = []
    for raw_signal in signals:
        signal = _normalize_signal(raw_signal)
        text = signal["signal_text"]
        category = signal["category"] if signal["category"] in SECTION_MAP.values() else "metric_preferences"
        if not text or text in compiled[category]:
            continue
        should_apply = signal["explicit"] or _existing_signal_occurrences(text) >= 1
        if should_apply:
            compiled[category].append(text)
            applied.append({"signal_text": text, "category": category})
        else:
            pending.append({"signal_text": text, "category": category})
    if not applied:
        return {"updated": False, "version": evaluation.get("version", 0), "applied": [], "pending": pending}
    result = _insert_evaluation_version(
        render_evaluation_markdown(compiled),
        source_type="topic_turn",
        source_ref=source_ref,
        reason="auto-update from topic turn signals",
    )
    return {
        "updated": True,
        "version": result["version"],
        "applied": applied,
        "pending": pending,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["show", "history", "rebuild"])
    args = parser.parse_args()
    if args.command == "show":
        print(json.dumps(show_evaluation(), ensure_ascii=False, indent=2))
        return
    if args.command == "history":
        print(json.dumps(list_evaluation_history(), ensure_ascii=False, indent=2))
        return
    print(json.dumps(rebuild_evaluation(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
