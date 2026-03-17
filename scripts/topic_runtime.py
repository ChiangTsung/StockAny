#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from charter import apply_charter_signals, load_charter_context
from common import CN_DISPLAY_CODE_RE, CN_SYMBOL_RE, TOPICS_DIR, US_SYMBOL_RE, dump_json, load_json, safe_filename, sha256_text, slugify, utc_now_iso
from db import connect, init_db
from evaluation import apply_evaluation_signals, detect_evaluation_signals, load_evaluation_context
from filings import review_documents
from intake import detect_charter_signal, extract_security_query
from market_data import quote_from_cache, refresh_market
from security_master import resolve_security_candidates


REPORT_SECTION_ORDER = [
    "investment_question",
    "topic_scope",
    "core_thesis",
    "key_evidence",
    "financial_operating_metrics",
    "valuation_market_expectation",
    "risks_disconfirming_evidence",
    "open_questions",
    "next_actions",
]

OPTIONAL_REPORT_SECTIONS = {
    "basket": ["members", "comparison_matrix"],
    "theme": ["members", "comparison_matrix"],
}

THEME_HINT_PATTERNS = [
    re.compile(r"([\u4e00-\u9fffA-Za-z0-9.+-]{2,30}?)(?:投资|赛道|板块|主题|行业|方向)"),
    re.compile(r"([\u4e00-\u9fffA-Za-z0-9.+-]{2,30}?(?:产业链|概念股|概念|链|模块))"),
]

GENERIC_THEME_STOP_WORDS = {
    "投资",
    "行业",
    "赛道",
    "板块",
    "主题",
    "方向",
    "个股",
    "标的",
    "公司",
    "股票",
    "A股",
    "美股",
    "研究",
    "分析",
    "报告",
    "逻辑",
    "估值",
    "风险",
}


def _topic_workspace(slug: str) -> Path:
    return TOPICS_DIR / slug


def _looks_like_security_query(query: str) -> bool:
    raw = query.strip()
    compact = raw.replace(" ", "")
    if not compact:
        return False
    upper = compact.upper()
    if CN_DISPLAY_CODE_RE.match(upper) or CN_SYMBOL_RE.match(upper):
        return True
    if US_SYMBOL_RE.match(upper) and upper == compact:
        return True
    if any("\u4e00" <= ch <= "\u9fff" for ch in raw) and len(raw) <= 8:
        return True
    return False


def _report_path(workspace: Path) -> Path:
    return workspace / "report.md"


def _normalize_topic_phrase(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip(" ，。！？、:：;；-")).strip()
    text = re.sub(r"^(?:但|那|就|先)?(?:这次|本次)?(?:要)?(?:放到|放在|归到|归入|作为)\s*", "", text)
    text = re.sub(r"^(?:这次|本次)?(?:重点是|重点看|主要看)\s*", "", text)
    for prefix in (
        "这次重点是",
        "重点是",
        "主要看",
        "先看",
        "我想看",
        "想看",
        "围绕",
        "关于",
    ):
        if text.startswith(prefix) and len(text) > len(prefix) + 1:
            text = text[len(prefix) :].strip()
            break
    for suffix in ("投资逻辑", "逻辑", "个股", "标的"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
            break
    for suffix in ("投资", "赛道", "板块", "主题", "行业", "方向", "概念股", "概念"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
            break
    return text.strip()


def _security_aliases(security: dict[str, Any] | None) -> set[str]:
    if not security:
        return set()
    aliases = {
        str(security.get("display_code", "")).strip(),
        str(security.get("company_name", "")).strip(),
        str(security.get("company_name_zh", "")).strip(),
        str(security.get("symbol", "")).strip(),
    }
    return {item for item in aliases if item}


def _extract_theme_title(message: str, security: dict[str, Any] | None = None) -> str:
    text = message.strip()
    if not text:
        return ""
    blocked = _security_aliases(security)
    candidates: list[str] = []
    for pattern in THEME_HINT_PATTERNS:
        for match in pattern.findall(text):
            candidate = _normalize_topic_phrase(match)
            if not candidate or candidate in GENERIC_THEME_STOP_WORDS or candidate in blocked:
                continue
            if len(candidate) < 2:
                continue
            candidates.append(candidate)
    if candidates:
        candidates.sort(key=lambda item: (len(item), item.count("产业链"), item.count("模块")), reverse=True)
        return candidates[0]
    return ""


def _report_meta_path(workspace: Path) -> Path:
    return workspace / "report.meta.json"


def _context_path(workspace: Path) -> Path:
    return workspace / "context.json"


def _turns_path(workspace: Path) -> Path:
    return workspace / "turns.jsonl"


def _materials_manifest_path(workspace: Path) -> Path:
    return workspace / "materials" / "manifest.json"


def _topic_member_securities(conn, topic_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tm.member_role, tm.confidence, s.*
        FROM topic_members tm
        JOIN securities s ON s.security_id = tm.security_id
        WHERE tm.topic_id = ?
        ORDER BY tm.member_role, s.display_code
        """,
        (topic_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _topic_aliases(conn, topic_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT alias FROM topic_aliases WHERE topic_id = ? ORDER BY alias",
        (topic_id,),
    ).fetchall()
    return [row["alias"] for row in rows]


def _load_topic_row(conn, topic_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT topic_id, slug, title, topic_type, status, workspace_path, summary, report_hash, created_at, updated_at
        FROM topics
        WHERE topic_id = ?
        """,
        (topic_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"topic {topic_id} not found")
    topic = dict(row)
    topic["member_securities"] = _topic_member_securities(conn, topic_id)
    topic["alias_keys"] = _topic_aliases(conn, topic_id)
    return topic


def _load_topic(conn, topic_id: str) -> dict[str, Any]:
    topic = _load_topic_row(conn, topic_id)
    workspace = Path(topic["workspace_path"])
    topic["report_path"] = str(_report_path(workspace))
    topic["report_markdown"] = _report_path(workspace).read_text(encoding="utf-8") if _report_path(workspace).exists() else ""
    topic["report_meta"] = load_json(_report_meta_path(workspace), default={"summary": "", "evidence_refs": []})
    topic["context"] = load_json(_context_path(workspace), default={})
    topic["materials"] = load_json(_materials_manifest_path(workspace), default={"items": []})
    return topic


def _unique_slug(conn, base_slug: str) -> str:
    slug = base_slug
    index = 2
    while conn.execute("SELECT 1 FROM topics WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base_slug}-{index}"
        index += 1
    return slug


def _normalize_alias(alias: str) -> str:
    return slugify(alias, default="topic")


def _report_sections_for_topic(topic_type: str) -> list[str]:
    return REPORT_SECTION_ORDER + OPTIONAL_REPORT_SECTIONS.get(topic_type, [])


def _default_section_body(section: str, title: str) -> str:
    defaults = {
        "investment_question": f"- 这份报告要回答关于 `{title}` 的核心投资问题是什么？",
        "topic_scope": "- 明确本主题覆盖的标的、时间跨度与讨论边界。",
        "core_thesis": "- 当前尚未沉淀出稳定 thesis，后续对话持续更新。",
        "key_evidence": "- 待补充关键证据、事实与资料出处。",
        "financial_operating_metrics": "- 待按 evaluation 偏好补充财务与经营指标。",
        "valuation_market_expectation": "- 待补充估值框架、市场预期与可比逻辑。",
        "risks_disconfirming_evidence": "- 待补充风险、证伪点与反例。",
        "open_questions": "- 待补充最关键未验证问题。",
        "next_actions": "- 下一步优先补资料或验证 thesis 的动作。",
        "members": "- 主题成员待补充。",
        "comparison_matrix": "- 对比维度待补充。",
    }
    return defaults.get(section, "- 待补充。")


def _render_report(title: str, topic_type: str, sections: dict[str, str]) -> str:
    lines = [f"# {title} Investment Report", ""]
    for section in _report_sections_for_topic(topic_type):
        lines.append(f"## {section}")
        body = sections.get(section, "").strip() or _default_section_body(section, title)
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _parse_report_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for raw_line in markdown.splitlines():
        if raw_line.startswith("## "):
            current = raw_line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        sections[current].append(raw_line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _default_report_meta(title: str) -> dict[str, Any]:
    return {
        "summary": f"{title} 的主题报告已初始化，等待对话逐步完善。",
        "evidence_refs": [],
        "last_change_note": "topic initialized",
    }


def _ensure_topic_workspace(topic: dict[str, Any]) -> None:
    workspace = Path(topic["workspace_path"])
    for path in (
        workspace,
        workspace / "materials",
        workspace / "issuers",
        workspace / "exports",
    ):
        path.mkdir(parents=True, exist_ok=True)
    report_path = _report_path(workspace)
    if not report_path.exists():
        report_path.write_text(_render_report(topic["title"], topic["topic_type"], {}), encoding="utf-8")
    meta_path = _report_meta_path(workspace)
    if not meta_path.exists():
        dump_json(meta_path, _default_report_meta(topic["title"]))
    manifest_path = _materials_manifest_path(workspace)
    if not manifest_path.exists():
        dump_json(manifest_path, {"items": []})
    context_path = _context_path(workspace)
    if not context_path.exists():
        dump_json(
            context_path,
            {
                "topic_id": topic["topic_id"],
                "title": topic["title"],
                "topic_type": topic["topic_type"],
                "status": topic["status"],
            },
        )


def _insert_aliases(conn, topic_id: str, aliases: list[str]) -> None:
    now = utc_now_iso()
    for alias in aliases:
        value = alias.strip()
        if not value:
            continue
        normalized = _normalize_alias(value)
        conn.execute(
            """
            INSERT OR IGNORE INTO topic_aliases (topic_id, alias, normalized_alias, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (topic_id, value, normalized, now),
        )


def _ensure_topic_member(conn, topic_id: str, security: dict[str, Any], member_role: str = "focus") -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO topic_members (topic_id, security_id, member_role, confidence, created_at)
        VALUES (?, ?, ?, 1.0, ?)
        """,
        (topic_id, security["security_id"], member_role, utc_now_iso()),
    )


def _record_similarity(conn, source_topic_id: str, target_topic_id: str, score: float, resolution: str) -> None:
    if source_topic_id == target_topic_id:
        return
    conn.execute(
        """
        INSERT INTO topic_similarity_links (source_topic_id, target_topic_id, similarity_score, resolution, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_topic_id, target_topic_id) DO UPDATE SET
            similarity_score = excluded.similarity_score,
            resolution = excluded.resolution,
            created_at = excluded.created_at
        """,
        (source_topic_id, target_topic_id, score, resolution, utc_now_iso()),
    )


def _best_theme_match(conn, query: str) -> tuple[dict[str, Any] | None, float]:
    rows = conn.execute(
        """
        SELECT topic_id, title, slug
        FROM topics
        WHERE status = 'active'
        ORDER BY updated_at DESC
        """
    ).fetchall()
    normalized_query = _normalize_alias(query)
    best_row = None
    best_score = 0.0
    for row in rows:
        title = row["title"]
        score = SequenceMatcher(None, normalized_query, _normalize_alias(title)).ratio()
        alias_rows = conn.execute(
            "SELECT normalized_alias FROM topic_aliases WHERE topic_id = ?",
            (row["topic_id"],),
        ).fetchall()
        for alias_row in alias_rows:
            score = max(score, SequenceMatcher(None, normalized_query, alias_row["normalized_alias"]).ratio())
        if score > best_score:
            best_score = score
            best_row = dict(row)
    return best_row, best_score


def _create_topic(
    conn,
    *,
    title: str,
    topic_type: str,
    aliases: list[str],
    member_security: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_slug = slugify(title)
    slug = _unique_slug(conn, base_slug)
    topic_id = f"topic_{slug.replace('.', '_').replace('-', '_')}"
    workspace = _topic_workspace(slug)
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO topics (topic_id, slug, title, topic_type, status, workspace_path, summary, report_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, '', ?, ?)
        """,
        (
            topic_id,
            slug,
            title,
            topic_type,
            str(workspace),
            f"{title} 的主题报告已初始化，等待对话逐步完善。",
            now,
            now,
        ),
    )
    _insert_aliases(conn, topic_id, aliases)
    if member_security:
        conn.execute(
            """
            INSERT INTO topic_members (topic_id, security_id, member_role, confidence, created_at)
            VALUES (?, ?, 'primary', 1.0, ?)
            """,
            (topic_id, member_security["security_id"], now),
        )
    topic = _load_topic_row(conn, topic_id)
    _ensure_topic_workspace(topic)
    return topic


def open_topic(query: str, message: str = "") -> dict[str, Any]:
    init_db()
    query = query.strip()
    message = message.strip()
    if not query and not message:
        raise ValueError("topic query is required")
    with connect() as conn:
        security_query = query if _looks_like_security_query(query) else extract_security_query(message)
        matches = []
        if security_query:
            try:
                matches = resolve_security_candidates(security_query, limit=5)
            except Exception:
                matches = []
        security = matches[0] if matches and matches[0]["confidence"] >= 0.95 else None
        theme_title = _extract_theme_title(message, security=security)
        if not theme_title and query and not _looks_like_security_query(query):
            theme_title = query

        if len(matches) > 1 and matches[0]["confidence"] < 0.99:
            return {
                "status": "needs_user_input",
                "topic_id": "",
                "topic_action": "needs_user_input",
                "needs_user_input": [
                    {
                        "kind": "pick_security",
                        "message": "查询命中了多个标的，请先明确要继续哪个标的主题。",
                        "options": matches,
                    }
                ],
                "dedupe": {"matched_topic_id": "", "similarity": 0.0, "action": "clarify"},
            }
        if theme_title:
            matched_topic, score = _best_theme_match(conn, theme_title)
            if matched_topic and score >= 0.88:
                _insert_aliases(
                    conn,
                    matched_topic["topic_id"],
                    [item for item in [query, theme_title, security_query] if item],
                )
                if security:
                    _ensure_topic_member(conn, matched_topic["topic_id"], security, member_role="focus")
                    _insert_aliases(
                        conn,
                        matched_topic["topic_id"],
                        [security["display_code"], security.get("company_name", ""), security.get("company_name_zh", "")],
                    )
                conn.commit()
                topic = _load_topic(conn, matched_topic["topic_id"])
                return {
                    "status": "ok",
                    "topic_id": topic["topic_id"],
                    "topic_action": "reused",
                    "topic_type": topic["topic_type"],
                    "topic": topic,
                    "needs_user_input": [],
                    "dedupe": {"matched_topic_id": topic["topic_id"], "similarity": round(score, 4), "action": "reuse_existing_topic"},
                }

            aliases = [item for item in [query, theme_title, security_query] if item]
            if security:
                aliases.extend([security["display_code"], security.get("company_name", ""), security.get("company_name_zh", "")])
            topic = _create_topic(
                conn,
                title=theme_title,
                topic_type="theme",
                aliases=aliases,
                member_security=security,
            )
            if security:
                conn.execute(
                    "UPDATE topic_members SET member_role = 'focus' WHERE topic_id = ? AND security_id = ?",
                    (topic["topic_id"], security["security_id"]),
                )
            conn.commit()
            topic = _load_topic(conn, topic["topic_id"])
            return {
                "status": "ok",
                "topic_id": topic["topic_id"],
                "topic_action": "created",
                "topic_type": topic["topic_type"],
                "topic": topic,
                "needs_user_input": [],
                "dedupe": {"matched_topic_id": "", "similarity": 0.0, "action": "created_new_topic"},
            }

        if security:
            row = conn.execute(
                """
                SELECT t.topic_id
                FROM topics t
                JOIN topic_members tm ON tm.topic_id = t.topic_id
                WHERE t.status = 'active' AND tm.security_id = ? AND tm.member_role = 'primary'
                LIMIT 1
                """,
                (security["security_id"],),
            ).fetchone()
            if row:
                _insert_aliases(
                    conn,
                    row["topic_id"],
                    [query, security["display_code"], security.get("company_name", ""), security.get("company_name_zh", "")],
                )
                conn.commit()
                topic = _load_topic(conn, row["topic_id"])
                return {
                    "status": "ok",
                    "topic_id": topic["topic_id"],
                    "topic_action": "reused",
                    "topic_type": topic["topic_type"],
                    "topic": topic,
                    "needs_user_input": [],
                    "dedupe": {"matched_topic_id": topic["topic_id"], "similarity": 1.0, "action": "reuse_existing_topic"},
                }
            title = security.get("company_name_zh") or security.get("company_name") or security["display_code"]
            topic = _create_topic(
                conn,
                title=title,
                topic_type="security",
                aliases=[query, security["display_code"], security.get("company_name", ""), security.get("company_name_zh", "")],
                member_security=security,
            )
            conn.commit()
            topic = _load_topic(conn, topic["topic_id"])
            return {
                "status": "ok",
                "topic_id": topic["topic_id"],
                "topic_action": "created",
                "topic_type": topic["topic_type"],
                "topic": topic,
                "needs_user_input": [],
                "dedupe": {"matched_topic_id": "", "similarity": 0.0, "action": "created_new_topic"},
            }

        matched_topic, score = _best_theme_match(conn, query)
        if matched_topic and score >= 0.88:
            _insert_aliases(conn, matched_topic["topic_id"], [query])
            conn.commit()
            topic = _load_topic(conn, matched_topic["topic_id"])
            return {
                "status": "ok",
                "topic_id": topic["topic_id"],
                "topic_action": "reused",
                "topic_type": topic["topic_type"],
                "topic": topic,
                "needs_user_input": [],
                "dedupe": {"matched_topic_id": topic["topic_id"], "similarity": round(score, 4), "action": "reuse_existing_topic"},
            }

        topic = _create_topic(conn, title=query, topic_type="theme", aliases=[query])
        if matched_topic and score >= 0.65:
            _record_similarity(conn, topic["topic_id"], matched_topic["topic_id"], score, "created_new_topic")
            dedupe = {"matched_topic_id": matched_topic["topic_id"], "similarity": round(score, 4), "action": "created_with_similar_topic"}
        else:
            dedupe = {"matched_topic_id": "", "similarity": 0.0, "action": "created_new_topic"}
        conn.commit()
        topic = _load_topic(conn, topic["topic_id"])
        return {
            "status": "ok",
            "topic_id": topic["topic_id"],
            "topic_action": "created",
            "topic_type": topic["topic_type"],
            "topic": topic,
            "needs_user_input": [],
            "dedupe": dedupe,
        }


def _load_manifest(workspace: Path) -> dict[str, Any]:
    return load_json(_materials_manifest_path(workspace), default={"items": []})


def _save_manifest(workspace: Path, manifest: dict[str, Any]) -> None:
    dump_json(_materials_manifest_path(workspace), manifest)


def _upsert_material_link(
    conn,
    *,
    topic_id: str,
    security_id: int | None,
    material_type: str,
    material_key: str,
    local_path: str,
    metadata: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO topic_material_links (topic_id, security_id, material_type, material_key, local_path, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_id, material_type, material_key) DO UPDATE SET
            local_path = excluded.local_path,
            metadata_json = excluded.metadata_json,
            created_at = excluded.created_at
        """,
        (
            topic_id,
            security_id,
            material_type,
            material_key,
            local_path,
            json.dumps(metadata, ensure_ascii=False),
            utc_now_iso(),
        ),
    )


def _write_topic_context(topic: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
    workspace = Path(topic["workspace_path"])
    payload = {
        "topic_id": topic["topic_id"],
        "title": topic["title"],
        "topic_type": topic["topic_type"],
        "status": topic["status"],
        "member_securities": [
            {
                "security_id": item["security_id"],
                "display_code": item["display_code"],
                "company_name": item.get("company_name", ""),
                "company_name_zh": item.get("company_name_zh", ""),
            }
            for item in topic.get("member_securities", [])
        ],
        "updated_at": utc_now_iso(),
    }
    if extra:
        payload.update(extra)
    dump_json(_context_path(workspace), payload)


def _copy_document_to_topic(doc: dict[str, Any], destination_dir: Path) -> str:
    source = Path(doc["local_path"])
    if not source.exists():
        return ""
    filename = safe_filename(source.name)
    target = destination_dir / filename
    if not target.exists():
        shutil.copy2(source, target)
    return str(target)


def _ensure_security_snapshot(topic: dict[str, Any], security: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    workspace = Path(topic["workspace_path"])
    issuer_dir = workspace / "issuers" / security["display_code"]
    for path in (issuer_dir, issuer_dir / "filings", issuer_dir / "notes", issuer_dir / "analysis"):
        path.mkdir(parents=True, exist_ok=True)
    dump_json(issuer_dir / "issuer.json", {key: security.get(key) for key in (
        "security_id",
        "market",
        "exchange",
        "symbol",
        "display_code",
        "company_name",
        "company_name_zh",
        "currency",
    )})
    materials: list[dict[str, Any]] = []
    materials.append(
        {
            "material_type": "issuer_snapshot",
            "material_key": f"issuer:{security['display_code']}",
            "local_path": str(issuer_dir / "issuer.json"),
            "metadata": {
                "display_code": security["display_code"],
                "company_name": security.get("company_name", ""),
                "company_name_zh": security.get("company_name_zh", ""),
            },
        }
    )

    errors: list[str] = []
    quote_result = None
    try:
        quote_response = refresh_market(security["display_code"])
        if quote_response.get("errors"):
            errors.extend(item["error"] for item in quote_response["errors"])
        if quote_response.get("quotes"):
            quote_result = quote_response["quotes"][0]
    except Exception as exc:
        errors.append(str(exc))
    quote_result = quote_result or quote_from_cache(security["display_code"])
    if quote_result:
        dump_json(issuer_dir / "market_snapshot.json", quote_result)
        materials.append(
            {
                "material_type": "market_snapshot",
                "material_key": f"quote:{security['display_code']}",
                "local_path": str(issuer_dir / "market_snapshot.json"),
                "metadata": {
                    "display_code": security["display_code"],
                    "fetched_at": quote_result.get("fetched_at", ""),
                },
            }
        )

    docs_response = review_documents(security["display_code"])
    documents = docs_response.get("documents", [])
    for doc in documents:
        copied = _copy_document_to_topic(doc, issuer_dir / "filings")
        if not copied:
            continue
        materials.append(
            {
                "material_type": "document",
                "material_key": f"document:{doc.get('source_url', copied)}",
                "local_path": copied,
                "metadata": {
                    "title": doc.get("title", ""),
                    "document_category": doc.get("document_category", ""),
                    "document_subtype": doc.get("document_subtype", ""),
                    "filed_at": doc.get("filed_at", ""),
                    "source_platform": doc.get("source_platform", ""),
                },
            }
        )
    if not documents:
        errors.append(f"no_local_documents_for_{security['display_code']}")
    return materials, errors


def _collect_topic_materials(topic: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    workspace = Path(topic["workspace_path"])
    manifest = _load_manifest(workspace)
    existing_items = {item["material_key"]: item for item in manifest.get("items", [])}
    errors: list[str] = []
    with connect() as conn:
        for security in topic.get("member_securities", []):
            materials, item_errors = _ensure_security_snapshot(topic, security)
            errors.extend(item_errors)
            for item in materials:
                existing_items[item["material_key"]] = item
                _upsert_material_link(
                    conn,
                    topic_id=topic["topic_id"],
                    security_id=security["security_id"],
                    material_type=item["material_type"],
                    material_key=item["material_key"],
                    local_path=item["local_path"],
                    metadata=item.get("metadata", {}),
                )
        conn.commit()
    updated_manifest = {"items": list(existing_items.values())}
    _save_manifest(workspace, updated_manifest)
    return updated_manifest, errors


def _bootstrap_questions(charter: dict[str, Any]) -> list[dict[str, Any]]:
    if charter.get("status") != "unset":
        return []
    return [
        {
            "kind": "charter_bootstrap",
            "message": "当前还没有正式投资宪章，建议补充单票仓位上限与卖出纪律。",
        }
    ]


def _should_auto_apply_detected_charter_signal(message: str) -> bool:
    lowered = message.lower()
    discipline_keywords = (
        "仓位",
        "单票",
        "止损",
        "止盈",
        "加仓",
        "减仓",
        "退出",
        "卖出",
        "不碰",
        "纪律",
        "回撤",
        "复盘",
        "教训",
        "position",
        "exit",
        "risk limit",
    )
    framing_keywords = (
        "以后",
        "应该",
        "必须",
        "不要",
        "默认",
        "原则",
        "规则",
        "习惯",
        "通常",
        "只在",
        "never",
        "always",
    )
    return any(keyword in lowered or keyword in message for keyword in discipline_keywords) and any(
        keyword in lowered or keyword in message for keyword in framing_keywords
    )


def _classify_research_mode(
    topic: dict[str, Any],
    manifest: dict[str, Any],
    material_errors: list[str],
) -> tuple[str, dict[str, Any]]:
    items = manifest.get("items", [])
    counts = {
        "issuer_snapshot": 0,
        "market_snapshot": 0,
        "document": 0,
    }
    for item in items:
        material_type = item.get("material_type", "")
        if material_type in counts:
            counts[material_type] += 1

    member_count = len(topic.get("member_securities", []))
    has_core_materials = counts["issuer_snapshot"] >= max(member_count, 1)
    has_supporting_materials = counts["document"] > 0 or counts["market_snapshot"] >= max(member_count, 1)
    missing_local_documents = [error for error in material_errors if error.startswith("no_local_documents_for_")]
    blocking_errors = [error for error in material_errors if not error.startswith("no_local_documents_for_")]

    mode = "analysis" if has_core_materials and has_supporting_materials and not blocking_errors else "collecting"
    reason = "materials_ready_for_analysis" if mode == "analysis" else "missing_core_or_supporting_materials"
    if missing_local_documents and mode == "analysis":
        reason = "analysis_with_partial_local_documents"

    guidance = (
        "已有本地财报或行情资料，优先围绕当前 report 分析、回答问题并更新结论；除非关键材料缺失，否则不要继续扩展式搜集。"
        if mode == "analysis"
        else "当前仍以补齐关键资料为主，但应只围绕 report 中尚未解决的缺口进行最小化补充。"
    )
    return mode, {
        "member_count": member_count,
        "material_counts": counts,
        "missing_local_documents": missing_local_documents,
        "blocking_errors": blocking_errors,
        "reason": reason,
        "guidance": guidance,
    }


def prepare_turn(*, topic_id: str | None = None, topic_query: str | None = None, message: str = "") -> dict[str, Any]:
    init_db()
    if topic_id:
        with connect() as conn:
            topic = _load_topic(conn, topic_id)
        topic_action = "reused"
        dedupe = {"matched_topic_id": topic_id, "similarity": 1.0, "action": "reuse_existing_topic"}
        status = "ok"
        needs_user_input: list[dict[str, Any]] = []
    else:
        result = open_topic(topic_query or "", message=message)
        if result["status"] != "ok":
            return result
        topic = result["topic"]
        topic_action = result["topic_action"]
        dedupe = result["dedupe"]
        status = result["status"]
        needs_user_input = result.get("needs_user_input", [])

    manifest, material_errors = _collect_topic_materials(topic)
    research_mode, research_state = _classify_research_mode(topic, manifest, material_errors)
    evaluation = load_evaluation_context()
    charter = load_charter_context()
    report_markdown = topic["report_markdown"]
    report_meta = topic["report_meta"]
    needs_user_input.extend(_bootstrap_questions(charter))

    extra_context = {
        "last_prepare_message": message,
        "last_material_errors": material_errors,
        "charter_version": charter.get("version", 0),
        "evaluation_version": evaluation.get("version", 0),
        "research_mode": research_mode,
        "research_state": research_state,
    }
    _write_topic_context(topic, extra_context)

    return {
        "status": status,
        "topic_id": topic["topic_id"],
        "topic_action": topic_action,
        "topic_type": topic["topic_type"],
        "report_path": topic["report_path"],
        "report_markdown": report_markdown,
        "report_summary": report_meta.get("summary", ""),
        "evaluation_markdown": evaluation["raw_markdown"],
        "evaluation_summary": evaluation.get("summary", ""),
        "charter_status": charter.get("status", "unset"),
        "charter_markdown": charter.get("raw_markdown", ""),
        "charter_summary": charter.get("summary", ""),
        "materials": manifest.get("items", []),
        "research_mode": research_mode,
        "research_state": research_state,
        "dedupe": dedupe,
        "needs_user_input": needs_user_input,
        "reply_brief": {
            "topic_title": topic["title"],
            "topic_summary": topic.get("summary", ""),
            "report_summary": report_meta.get("summary", ""),
            "user_message": message,
            "analysis_priority": research_mode == "analysis",
            "analysis_guidance": research_state["guidance"],
            "material_error_count": len(material_errors),
            "material_errors": material_errors[:10],
        },
    }


def _apply_report_patch(topic: dict[str, Any], report_patch: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    workspace = Path(topic["workspace_path"])
    sections = _parse_report_sections(topic["report_markdown"])
    changed_sections: list[str] = []
    for item in report_patch.get("replace_sections", []):
        section_id = item.get("section_id", "").strip()
        if section_id not in _report_sections_for_topic(topic["topic_type"]):
            continue
        sections[section_id] = (item.get("markdown") or "").strip()
        changed_sections.append(section_id)
    rendered = _render_report(topic["title"], topic["topic_type"], sections)
    meta = load_json(_report_meta_path(workspace), default=_default_report_meta(topic["title"]))
    evidence_refs = meta.get("evidence_refs", [])
    for ref in report_patch.get("append_evidence_refs", []):
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    meta["evidence_refs"] = evidence_refs
    meta["summary"] = report_patch.get("updated_summary") or meta.get("summary") or topic.get("summary") or ""
    return rendered, meta, changed_sections


def commit_turn(topic_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        topic = _load_topic(conn, topic_id)
    workspace = Path(topic["workspace_path"])
    report_before = topic["report_markdown"]
    report_hash_before = sha256_text(report_before)
    report_patch = payload.get("report_patch") or {}
    rendered_report, report_meta, changed_sections = _apply_report_patch(topic, report_patch)
    report_hash_after = sha256_text(rendered_report)
    _report_path(workspace).write_text(rendered_report, encoding="utf-8")
    report_meta["last_change_note"] = payload.get("change_note") or "topic turn committed"
    report_meta["updated_at"] = utc_now_iso()
    dump_json(_report_meta_path(workspace), report_meta)

    charter_signals = payload.get("charter_signals") or []
    if not charter_signals:
        detected = detect_charter_signal(payload.get("user_message", ""))
        if detected and _should_auto_apply_detected_charter_signal(payload.get("user_message", "")):
            charter_signals = [detected]
    evaluation_signals = payload.get("evaluation_signals") or detect_evaluation_signals(payload.get("user_message", ""))

    source_ref = f"{topic_id}:{utc_now_iso()}"
    charter_update = apply_charter_signals(charter_signals, source_ref=source_ref)
    evaluation_update = apply_evaluation_signals(evaluation_signals, source_ref=source_ref)

    turn_payload = {
        "created_at": utc_now_iso(),
        "user_message": payload.get("user_message", ""),
        "assistant_reply_markdown": payload.get("assistant_reply_markdown", ""),
        "change_note": payload.get("change_note", ""),
        "changed_sections": changed_sections,
        "charter_signals": charter_signals,
        "evaluation_signals": evaluation_signals,
        "report_hash_before": report_hash_before,
        "report_hash_after": report_hash_after,
    }
    with _turns_path(workspace).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(turn_payload, ensure_ascii=False) + "\n")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO topic_turns
            (topic_id, user_message, assistant_reply_markdown, report_patch_json, charter_signals_json, evaluation_signals_json, change_note, changed_sections_json, report_hash_before, report_hash_after, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                payload.get("user_message", ""),
                payload.get("assistant_reply_markdown", ""),
                json.dumps(report_patch, ensure_ascii=False),
                json.dumps(charter_signals, ensure_ascii=False),
                json.dumps(evaluation_signals, ensure_ascii=False),
                payload.get("change_note", ""),
                json.dumps(changed_sections, ensure_ascii=False),
                report_hash_before,
                report_hash_after,
                utc_now_iso(),
            ),
        )
        conn.execute(
            """
            UPDATE topics
            SET summary = ?, report_hash = ?, updated_at = ?
            WHERE topic_id = ?
            """,
            (report_meta.get("summary", ""), report_hash_after, utc_now_iso(), topic_id),
        )
        conn.commit()
        topic = _load_topic(conn, topic_id)

    current_charter = load_charter_context()
    current_evaluation = load_evaluation_context()
    _write_topic_context(
        topic,
        {
            "last_change_note": payload.get("change_note", ""),
            "report_hash": report_hash_after,
            "charter_version": current_charter.get("version", 0),
            "evaluation_version": current_evaluation.get("version", 0),
        },
    )
    return {
        "topic_id": topic_id,
        "report_path": str(_report_path(workspace)),
        "report_summary": report_meta.get("summary", ""),
        "changed_sections": changed_sections,
        "report_hash_before": report_hash_before,
        "report_hash_after": report_hash_after,
        "charter_updated": bool(charter_update.get("updated")),
        "charter_update": charter_update,
        "evaluation_updated": bool(evaluation_update.get("updated")),
        "evaluation_update": evaluation_update,
    }


def show_topic(topic_id: str) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        topic = _load_topic(conn, topic_id)
    charter = load_charter_context()
    evaluation = load_evaluation_context()
    return {
        "topic_id": topic["topic_id"],
        "title": topic["title"],
        "topic_type": topic["topic_type"],
        "status": topic["status"],
        "workspace_path": topic["workspace_path"],
        "summary": topic.get("summary", ""),
        "member_securities": topic.get("member_securities", []),
        "alias_keys": topic.get("alias_keys", []),
        "report_path": topic["report_path"],
        "report_markdown": topic["report_markdown"],
        "report_meta": topic["report_meta"],
        "materials": topic["materials"].get("items", []),
        "context": topic["context"],
        "current_charter": {
            "version": charter.get("version", 0),
            "status": charter.get("status", "unset"),
            "summary": charter.get("summary", ""),
        },
        "current_evaluation": {
            "version": evaluation.get("version", 0),
            "status": evaluation.get("status", "active"),
            "summary": evaluation.get("summary", ""),
        },
    }


def archive_topic(topic_id: str) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        topic = _load_topic(conn, topic_id)
        conn.execute(
            "UPDATE topics SET status = 'archived', updated_at = ? WHERE topic_id = ?",
            (utc_now_iso(), topic_id),
        )
        conn.commit()
        topic = _load_topic(conn, topic_id)
    _write_topic_context(topic, {"status": "archived"})
    return {"topic_id": topic_id, "status": "archived", "workspace_path": topic["workspace_path"]}
