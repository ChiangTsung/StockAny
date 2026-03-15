#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import (
    PENDING_REVIEW_DIR,
    fetch_bytes,
    fetch_json,
    safe_filename,
    sha256_text,
    sha256_bytes,
    utc_now_iso,
    write_bytes,
)
from db import connect, dossier_dir, init_db
from security_master import resolve_security_or_raise

try:
    import akshare as ak
except Exception:  # pragma: no cover - runtime dependency
    ak = None


TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
RECENT_FORMS = {"10-K", "10-Q", "8-K"}

CNINFO_CATEGORY_SPECS = [
    {"category": "年报", "keyword": "", "document_category": "financial_report", "document_subtype": "annual_report"},
    {"category": "半年报", "keyword": "", "document_category": "financial_report", "document_subtype": "semiannual_report"},
    {"category": "一季报", "keyword": "", "document_category": "financial_report", "document_subtype": "q1_report"},
    {"category": "三季报", "keyword": "", "document_category": "financial_report", "document_subtype": "q3_report"},
    {"category": "业绩预告", "keyword": "", "document_category": "material_event", "document_subtype": "earnings_preannouncement"},
    {"category": "股权变动", "keyword": "", "document_category": "capital_markets", "document_subtype": "shareholding_change"},
    {"category": "股权变动", "keyword": "回购", "document_category": "capital_markets", "document_subtype": "buyback"},
    {"category": "其他融资", "keyword": "", "document_category": "capital_markets", "document_subtype": "private_placement"},
    {"category": "日常经营", "keyword": "合同", "document_category": "material_event", "document_subtype": "major_contract"},
    {"category": "公司治理", "keyword": "问询", "document_category": "regulatory", "document_subtype": "regulatory_reply"},
    {"category": "公司治理", "keyword": "回复", "document_category": "regulatory", "document_subtype": "regulatory_reply"},
]


def active_securities() -> list[dict[str, Any]]:
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


def _write_review_note(security: dict[str, Any], doc: dict[str, str], local_path: Path) -> Path:
    folder = PENDING_REVIEW_DIR / security["display_code"]
    folder.mkdir(parents=True, exist_ok=True)
    doc_key = sha256_text(f"{doc['source_url']}|{doc['title']}")[:10]
    note_base = safe_filename(f"{doc['document_subtype']}-{doc['filed_at'] or 'undated'}-{doc_key}")
    note_path = folder / f"{note_base}.md"
    content = [
        f"# {security['display_code']} Pending Review",
        "",
        f"- market: {security['market']}",
        f"- exchange: {security['exchange']}",
        f"- title: {doc['title']}",
        f"- document_category: {doc['document_category']}",
        f"- document_subtype: {doc['document_subtype']}",
        f"- filed_at: {doc['filed_at']}",
        f"- period_end: {doc['period_end']}",
        f"- source_platform: {doc['source_platform']}",
        f"- source_url: {doc['source_url']}",
        f"- local_path: {local_path}",
        "",
        "请阅读原文后再决定是否更新 thesis 或投资宪章。",
    ]
    note_path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return note_path


def _download_document(security: dict[str, Any], doc: dict[str, str]) -> dict[str, Any]:
    blob = fetch_bytes(doc["source_url"])
    digest = sha256_bytes(blob)
    ext_match = re.search(r"\.([A-Za-z0-9]+)(?:$|\?)", doc["source_url"])
    ext = ext_match.group(1) if ext_match else "html"
    doc_key = sha256_text(f"{doc['source_url']}|{doc['title']}")[:10]
    filename = safe_filename(f"{doc['document_subtype']}-{doc['filed_at'] or 'undated'}-{doc_key}") + f".{ext}"
    local_path = dossier_dir(security["display_code"]) / "sources" / filename
    write_bytes(local_path, blob)
    return {"sha256": digest, "local_path": local_path}


def _upsert_document(security: dict[str, Any], doc: dict[str, str]) -> dict[str, Any] | None:
    downloaded = _download_document(security, doc)
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM documents WHERE source_url = ? AND sha256 = ?",
            (doc["source_url"], downloaded["sha256"]),
        ).fetchone()
        if existing:
            return None
        conn.execute(
            """
            INSERT INTO documents
            (ticker, security_id, market, exchange, doc_type, period_end, filed_at, source_url, local_path, sha256, review_status, created_at, document_category, document_subtype, title, source_platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                security["display_code"],
                security["security_id"],
                security["market"],
                security["exchange"],
                doc["doc_type"],
                doc["period_end"],
                doc["filed_at"],
                doc["source_url"],
                str(downloaded["local_path"]),
                downloaded["sha256"],
                utc_now_iso(),
                doc["document_category"],
                doc["document_subtype"],
                doc["title"],
                doc["source_platform"],
            ),
        )
        conn.commit()
    review_note = _write_review_note(security, doc, downloaded["local_path"])
    return {
        "title": doc["title"],
        "doc_type": doc["doc_type"],
        "filed_at": doc["filed_at"],
        "source_platform": doc["source_platform"],
        "local_path": str(downloaded["local_path"]),
        "review_note": str(review_note),
    }


def _load_ticker_map() -> dict[str, str]:
    payload = fetch_json(TICKER_MAP_URL)
    return {
        str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
        for item in payload.values()
        if item.get("ticker")
    }


def _get_cik(symbol: str) -> str:
    mapping = _load_ticker_map()
    cik = mapping.get(symbol.upper())
    if not cik:
        raise RuntimeError(f"SEC CIK not found for {symbol}")
    return cik


def _recent_filings(cik: str) -> list[dict[str, str]]:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    payload = fetch_json(url)
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession = recent.get("accessionNumber", [])
    primary = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    items = []
    for idx, form in enumerate(forms):
        if form not in RECENT_FORMS:
            continue
        items.append(
            {
                "form": form,
                "accession": accession[idx],
                "primary_document": primary[idx],
                "filed_at": filing_dates[idx] or "",
                "period_end": report_dates[idx] or "",
                "cik": cik,
            }
        )
    return items


def _index_json_url(cik: str, accession: str) -> str:
    access_no_dash = accession.replace("-", "")
    cik_num = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{access_no_dash}/index.json"


def _classify_us_document(doc_type: str, filed_at: str, source_url: str, primary_document: str = "") -> dict[str, str]:
    if doc_type == "10-K":
        return {
            "doc_type": doc_type,
            "document_category": "financial_report",
            "document_subtype": "annual_report",
            "title": f"{doc_type} filed {filed_at}",
            "source_platform": "sec",
        }
    if doc_type == "10-Q":
        subtype = "semiannual_report"
        if "0331" in source_url or "03-31" in source_url:
            subtype = "q1_report"
        if "0930" in source_url or "09-30" in source_url:
            subtype = "q3_report"
        return {
            "doc_type": doc_type,
            "document_category": "financial_report",
            "document_subtype": subtype,
            "title": f"{doc_type} filed {filed_at}",
            "source_platform": "sec",
        }
    return {
        "doc_type": doc_type,
        "document_category": "material_event",
        "document_subtype": "other_material",
        "title": primary_document or f"{doc_type} filed {filed_at}",
        "source_platform": "sec",
    }


def _collect_us_documents(item: dict[str, str]) -> list[dict[str, str]]:
    access_no_dash = item["accession"].replace("-", "")
    cik_num = str(int(item["cik"]))
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{access_no_dash}"
    docs = [
        {
            **_classify_us_document(item["form"], item["filed_at"], item["primary_document"], item["primary_document"]),
            "source_url": f"{base}/{item['primary_document']}",
            "filed_at": item["filed_at"],
            "period_end": item["period_end"],
        }
    ]
    if item["form"] != "8-K":
        return docs
    try:
        index_payload = fetch_json(_index_json_url(item["cik"], item["accession"]))
    except Exception:
        return docs
    for entry in index_payload.get("directory", {}).get("item", []):
        name = entry.get("name", "")
        if not name.endswith((".htm", ".html", ".txt", ".xml")):
            continue
        if any(token in name.lower() for token in ("ex99", "99-1", "99-2", "ex-99")):
            doc_type = "EX-99.1" if "99.1" in name or "99-1" in name else "EX-99.2"
            docs.append(
                {
                    "doc_type": doc_type,
                    "document_category": "material_event",
                    "document_subtype": "other_material",
                    "title": name,
                    "source_platform": "sec",
                    "source_url": f"{base}/{name}",
                    "filed_at": item["filed_at"],
                    "period_end": item["period_end"],
                }
            )
    return docs


def _sync_us_filings(security: dict[str, Any]) -> list[dict[str, Any]]:
    cik = _get_cik(security["symbol"])
    recent = _recent_filings(cik)
    new_docs = []
    for item in recent[:15]:
        for doc in _collect_us_documents(item):
            created = _upsert_document(security, doc)
            if created:
                new_docs.append(created)
    return new_docs


def _cninfo_start_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y%m%d")


def _cninfo_end_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _normalize_cninfo_doc(row: dict[str, Any], spec: dict[str, str]) -> dict[str, str]:
    title = str(row.get("公告标题") or row.get("标题") or "")
    filed_at = str(row.get("公告时间") or row.get("发布时间") or row.get("日期") or "")
    source_url = str(row.get("公告链接") or row.get("链接") or row.get("url") or "").replace(" ", "%20")
    subtype = spec["document_subtype"]
    if "摘要" in title and subtype in {"annual_report", "semiannual_report", "q1_report", "q3_report"}:
        subtype = f"{subtype}_summary"
    return {
        "doc_type": "CNINFO",
        "document_category": spec["document_category"],
        "document_subtype": subtype,
        "title": title,
        "source_platform": "cninfo",
        "source_url": source_url,
        "filed_at": filed_at,
        "period_end": "",
    }


def _sync_cn_filings(security: dict[str, Any]) -> list[dict[str, Any]]:
    if ak is None:
        raise RuntimeError("AKShare is required for A-share filings. Install with: python3 -m pip install --user akshare pypinyin")
    seen_urls = set()
    candidates = []
    for spec in CNINFO_CATEGORY_SPECS:
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=security["symbol"],
                market="沪深京",
                keyword=spec["keyword"],
                category=spec["category"],
                start_date=_cninfo_start_date(),
                end_date=_cninfo_end_date(),
            )
        except Exception:
            continue
        if df is None or df.empty:
            continue
        for row in df.to_dict(orient="records"):
            doc = _normalize_cninfo_doc(row, spec)
            if not doc["title"] or not doc["source_url"]:
                continue
            if doc["source_url"] in seen_urls:
                continue
            seen_urls.add(doc["source_url"])
            candidates.append(doc)
    candidates.sort(key=lambda item: (item["filed_at"], item["title"]), reverse=True)
    new_docs = []
    for doc in candidates[:40]:
        created = _upsert_document(security, doc)
        if created:
            new_docs.append(created)
    return new_docs


def sync_filings(target: str) -> dict[str, Any]:
    init_db()
    securities = active_securities() if target == "all-active" else [resolve_security_or_raise(target)]
    synced = []
    errors = []
    for security in securities:
        try:
            if security["market"] == "CN":
                new_docs = _sync_cn_filings(security)
            else:
                new_docs = _sync_us_filings(security)
            synced.append({"ticker": security["display_code"], "market": security["market"], "new_documents": new_docs})
        except Exception as exc:
            errors.append({"ticker": security["display_code"], "market": security["market"], "error": str(exc)})
    return {"synced": synced, "errors": errors}


def review_documents(ticker: str) -> dict[str, Any]:
    init_db()
    security = resolve_security_or_raise(ticker)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ticker, market, exchange, title, document_category, document_subtype, period_end, filed_at, source_platform, source_url, local_path, review_status
            FROM documents
            WHERE security_id = ?
            ORDER BY filed_at DESC, id DESC
            """,
            (security["security_id"],),
        ).fetchall()
    return {"ticker": security["display_code"], "market": security["market"], "documents": [dict(row) for row in rows]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    print(json.dumps(sync_filings(args.ticker), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
