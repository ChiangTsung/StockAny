#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import ASSETS_DIR, CHARTER_CANDIDATES_DIR, utc_now_iso
from db import connect, ensure_unset_charter, init_db


SECTION_MAP = {
    "investment_goals": "investment_goals",
    "allowed_styles": "allowed_styles",
    "position_sizing_rules": "position_sizing_rules",
    "ban_conditions": "ban_conditions",
    "add_conditions": "add_conditions",
    "trim_conditions": "trim_conditions",
    "exit_conditions": "exit_conditions",
    "risk_limits": "risk_limits",
    "experience_patterns": "experience_patterns",
    "reflection_rules": "reflection_rules",
}

KIND_TO_SECTION = {
    "style": "allowed_styles",
    "sizing": "position_sizing_rules",
    "ban": "ban_conditions",
    "add": "add_conditions",
    "trim": "trim_conditions",
    "exit": "exit_conditions",
    "risk": "risk_limits",
    "reflection": "reflection_rules",
}

ACTIVE_CHARTER_PATH = ASSETS_DIR / "charter-active.md"


def _versioned_charter_path(version: int) -> Path:
    return ASSETS_DIR / f"charter-active-v{version}.md"


def _sync_charter_files(raw_markdown: str, version: int) -> None:
    ACTIVE_CHARTER_PATH.write_text(raw_markdown, encoding="utf-8")
    _versioned_charter_path(version).write_text(raw_markdown, encoding="utf-8")


def compile_charter_markdown(raw_markdown: str) -> dict[str, list[str]]:
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


def render_charter_markdown(compiled: dict[str, list[str]]) -> str:
    lines = ["# StockAny Charter", ""]
    for section in SECTION_MAP.values():
        lines.append(f"## {section}")
        lines.extend(f"- {value}" for value in compiled.get(section, []))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def summarize_charter(compiled: dict[str, list[str]], limit: int = 4) -> str:
    items: list[str] = []
    for section in SECTION_MAP.values():
        items.extend(compiled.get(section, []))
        if len(items) >= limit:
            break
    return "；".join(items[:limit])


def _active_or_latest_charter(conn) -> dict[str, Any]:
    row = conn.execute(
        "SELECT version, status, raw_markdown, compiled_rules_json, active, created_at FROM charters WHERE active = 1 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT version, status, raw_markdown, compiled_rules_json, active, created_at FROM charters ORDER BY version DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else {}


def _insert_charter_version(
    raw_markdown: str,
    *,
    status: str = "active",
    activate: bool = True,
) -> dict[str, Any]:
    init_db()
    compiled = compile_charter_markdown(raw_markdown)
    with connect() as conn:
        if activate:
            conn.execute("UPDATE charters SET active = 0, status = 'superseded' WHERE active = 1")
        cursor = conn.execute(
            """
            INSERT INTO charters (status, raw_markdown, compiled_rules_json, active, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (status, raw_markdown, json.dumps(compiled, ensure_ascii=False), 1 if activate else 0, utc_now_iso()),
        )
        conn.commit()
        version = int(cursor.lastrowid)
    _sync_charter_files(raw_markdown, version)
    return {"version": version, "status": status, "compiled": compiled}


def load_charter_context() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        ensure_unset_charter(conn)
        row = _active_or_latest_charter(conn)
    if not row:
        return {
            "version": 0,
            "status": "unset",
            "active": 0,
            "raw_markdown": "",
            "compiled_rules_json": {},
            "source_file": str(ACTIVE_CHARTER_PATH),
            "versioned_source_file": "",
            "created_at": "",
        }

    row["compiled_rules_json"] = json.loads(row["compiled_rules_json"] or "{}")
    raw_markdown = row.get("raw_markdown") or ""
    version = int(row.get("version") or 0)
    versioned_path = _versioned_charter_path(version)

    if raw_markdown:
        active_text = ACTIVE_CHARTER_PATH.read_text(encoding="utf-8") if ACTIVE_CHARTER_PATH.exists() else ""
        versioned_text = versioned_path.read_text(encoding="utf-8") if versioned_path.exists() else ""
        if active_text != raw_markdown or versioned_text != raw_markdown:
            _sync_charter_files(raw_markdown, version)

    row["source_file"] = str(ACTIVE_CHARTER_PATH)
    row["versioned_source_file"] = str(versioned_path)
    row["summary"] = summarize_charter(row["compiled_rules_json"])
    return row


def show_charter() -> dict[str, Any]:
    return load_charter_context()


def set_charter_from_file(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    result = _insert_charter_version(raw, status="active", activate=True)
    return {
        "status": "active",
        "compiled": result["compiled"],
        "source_file": str(ACTIVE_CHARTER_PATH),
        "version": result["version"],
    }


def list_charter_history() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT version, status, active, created_at
            FROM charters
            ORDER BY version DESC
            """
        ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        versioned_path = _versioned_charter_path(int(item["version"]))
        item["versioned_source_file"] = str(versioned_path)
        history.append(item)
    return {"versions": history}


def switch_charter_version(version: int) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT version, status, raw_markdown, compiled_rules_json, created_at
            FROM charters
            WHERE version = ?
            """,
            (version,),
        ).fetchone()
        if not row:
            raise ValueError(f"charter version {version} not found")
        conn.execute("UPDATE charters SET active = 0, status = 'superseded' WHERE active = 1")
        conn.execute("UPDATE charters SET active = 1, status = 'active' WHERE version = ?", (version,))
        conn.commit()
    raw_markdown = row["raw_markdown"] or ""
    if raw_markdown:
        _sync_charter_files(raw_markdown, int(row["version"]))
    return show_charter()


def apply_charter_signals(signals: list[dict[str, Any]], source_ref: str = "") -> dict[str, Any]:
    if not signals:
        return {"updated": False, "version": 0, "applied": []}
    charter = load_charter_context()
    compiled = charter.get("compiled_rules_json", {}) or {}
    for section in SECTION_MAP.values():
        compiled.setdefault(section, [])
    applied = []
    for signal in signals:
        candidate_text = (signal.get("candidate_text") or "").strip()
        candidate_kind = signal.get("candidate_kind") or ""
        if not candidate_text or candidate_kind not in KIND_TO_SECTION:
            continue
        section = KIND_TO_SECTION[candidate_kind]
        if candidate_text in compiled[section]:
            continue
        compiled[section].append(candidate_text)
        applied.append({"candidate_kind": candidate_kind, "candidate_text": candidate_text})
    if not applied:
        return {"updated": False, "version": charter.get("version", 0), "applied": []}
    raw_markdown = render_charter_markdown(compiled)
    result = _insert_charter_version(raw_markdown, status="active", activate=True)
    return {
        "updated": True,
        "version": result["version"],
        "applied": applied,
        "source_ref": source_ref,
    }


def add_candidate(source_type: str, source_ref: str, candidate_text: str, candidate_kind: str, confidence: float) -> int:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT candidate_id FROM charter_candidates
            WHERE source_ref = ? AND candidate_text = ? AND candidate_kind = ? AND review_status = 'pending'
            """,
            (source_ref, candidate_text, candidate_kind),
        ).fetchone()
        if row:
            return int(row["candidate_id"])
        cursor = conn.execute(
            """
            INSERT INTO charter_candidates
            (source_type, source_ref, candidate_text, candidate_kind, confidence, review_status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (source_type, source_ref, candidate_text, candidate_kind, confidence, utc_now_iso()),
        )
        conn.commit()
        candidate_id = int(cursor.lastrowid)
    note = CHARTER_CANDIDATES_DIR / f"candidate-{candidate_id}.md"
    note.write_text(
        "\n".join(
            [
                f"# Charter Candidate {candidate_id}",
                "",
                f"- source_type: {source_type}",
                f"- source_ref: {source_ref}",
                f"- candidate_kind: {candidate_kind}",
                f"- confidence: {confidence}",
                "",
                candidate_text,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return candidate_id


def list_candidates() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT candidate_id, source_type, source_ref, candidate_text, candidate_kind, confidence, review_status, created_at
            FROM charter_candidates
            ORDER BY created_at DESC, candidate_id DESC
            """
        ).fetchall()
    return {"candidates": [dict(row) for row in rows]}


def review_candidate(candidate_id: int) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT candidate_id, source_type, source_ref, candidate_text, candidate_kind, confidence, review_status, created_at
            FROM charter_candidates
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"candidate {candidate_id} not found")
    return dict(row)


def merge_candidates(candidate_ids: list[int]) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT candidate_id, candidate_text, candidate_kind, review_status
            FROM charter_candidates
            WHERE candidate_id IN ({",".join("?" for _ in candidate_ids)})
            ORDER BY candidate_id
            """,
            tuple(candidate_ids),
        ).fetchall()
        if len(rows) != len(candidate_ids):
            raise ValueError("some candidate ids were not found")
        latest = _active_or_latest_charter(conn)
        status = latest.get("status", "unset")
        compiled = json.loads(latest.get("compiled_rules_json", "{}") or "{}")
        for section in SECTION_MAP.values():
            compiled.setdefault(section, [])
        merged_ids = []
        for row in rows:
            if row["review_status"] not in {"pending", "accepted"}:
                continue
            section = KIND_TO_SECTION[row["candidate_kind"]]
            if row["candidate_text"] not in compiled[section]:
                compiled[section].append(row["candidate_text"])
            merged_ids.append(int(row["candidate_id"]))
        raw_markdown = render_charter_markdown(compiled)
        if latest.get("active"):
            conn.execute("UPDATE charters SET active = 0, status = 'superseded' WHERE active = 1")
            new_status = "active"
            active = 1
        else:
            new_status = "draft" if status in {"unset", "draft"} else "active"
            active = 1 if new_status == "active" else 0
        cursor = conn.execute(
            """
            INSERT INTO charters (status, raw_markdown, compiled_rules_json, active, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_status, raw_markdown, json.dumps(compiled, ensure_ascii=False), active, utc_now_iso()),
        )
        if merged_ids:
            conn.execute(
                f"UPDATE charter_candidates SET review_status = 'merged' WHERE candidate_id IN ({','.join('?' for _ in merged_ids)})",
                tuple(merged_ids),
        )
        conn.commit()
        version = int(cursor.lastrowid)
    _sync_charter_files(raw_markdown, version)
    return {
        "merged_candidate_ids": merged_ids,
        "charter_status": new_status,
        "compiled_rules": compiled,
        "source_file": str(ACTIVE_CHARTER_PATH),
        "version": version,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["show"])
    args = parser.parse_args()
    print(json.dumps(show_charter(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
