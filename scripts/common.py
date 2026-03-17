from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
STATE_DIR = ROOT / "state"
CACHE_DIR = STATE_DIR / "cache"
INBOX_DIR = ROOT / "inbox"
PENDING_REVIEW_DIR = INBOX_DIR / "pending-review"
CHARTER_CANDIDATES_DIR = INBOX_DIR / "charter-candidates"
RESEARCH_DIR = ROOT / "research"
TOPICS_DIR = RESEARCH_DIR / "topics"
LEGACY_DOSSIERS_DIR = RESEARCH_DIR / "legacy-dossiers"
ASSETS_DIR = ROOT / "assets"
REFERENCES_DIR = ROOT / "references"
DB_PATH = STATE_DIR / "stockany.db"
CONFIG_PATH = STATE_DIR / "config.json"
JOURNAL_DIR = STATE_DIR / "journal"
REPORTS_DIR = STATE_DIR / "reports"
EVALUATION_ACTIVE_PATH = ASSETS_DIR / "evaluation-active.md"
EVALUATION_TEMPLATE_PATH = ASSETS_DIR / "evaluation-template.md"
EVALUATION_CACHE_PATH = CACHE_DIR / "evaluation.json"

CN_DISPLAY_CODE_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$", re.IGNORECASE)
CN_SYMBOL_RE = re.compile(r"^\d{6}$")
US_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.^-]{0,9}$")


DEFAULT_CONFIG: dict[str, Any] = {
    "http": {
        "user_agent": "StockAny stockany@example.com",
        "timeout_seconds": 30,
    },
}


def bootstrap_path() -> None:
    scripts = str(SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def ensure_runtime_layout() -> None:
    for path in (
        STATE_DIR,
        CACHE_DIR,
        PENDING_REVIEW_DIR,
        CHARTER_CANDIDATES_DIR,
        JOURNAL_DIR,
        REPORTS_DIR,
        RESEARCH_DIR,
        TOPICS_DIR,
        LEGACY_DOSSIERS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def today_str() -> str:
    return utc_now().date().isoformat()


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def normalize_ticker(value: str | None) -> str:
    return normalize_symbol(value)


def normalize_symbol(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip().upper()
    raw = raw.replace(" ", "")
    match = CN_DISPLAY_CODE_RE.match(raw)
    if match:
        return f"{match.group(1)}.{match.group(2).upper()}"
    if CN_SYMBOL_RE.match(raw):
        return raw
    return re.sub(r"[^A-Z0-9.^-]", "", raw)


def detect_market(value: str | None) -> str:
    symbol = normalize_symbol(value)
    if not symbol:
        return ""
    if CN_DISPLAY_CODE_RE.match(symbol) or CN_SYMBOL_RE.match(symbol):
        return "CN"
    if US_SYMBOL_RE.match(symbol):
        return "US"
    return ""


def display_code_to_symbol(display_code: str) -> str:
    normalized = normalize_symbol(display_code)
    match = CN_DISPLAY_CODE_RE.match(normalized)
    if match:
        return match.group(1)
    return normalized


def infer_cn_exchange(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    match = CN_DISPLAY_CODE_RE.match(normalized)
    if match:
        suffix = match.group(2).upper()
        return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[suffix]
    if not CN_SYMBOL_RE.match(normalized):
        return ""
    if normalized.startswith(("600", "601", "603", "605", "688", "689")):
        return "SSE"
    if normalized.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZSE"
    if normalized.startswith(
        (
            "430",
            "831",
            "832",
            "833",
            "834",
            "835",
            "836",
            "837",
            "838",
            "839",
            "870",
            "871",
            "872",
            "873",
            "920",
        )
    ):
        return "BSE"
    return ""


def format_display_code(market: str, symbol: str, exchange: str = "") -> str:
    market = (market or "").upper()
    symbol = normalize_symbol(symbol)
    if market == "CN":
        base_symbol = display_code_to_symbol(symbol)
        exchange_name = (exchange or infer_cn_exchange(base_symbol)).upper()
        suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ", "SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(
            exchange_name, ""
        )
        return f"{base_symbol}.{suffix}" if suffix else base_symbol
    return symbol.upper()


def cache_quote_name(market: str, display_code: str) -> str:
    return f"quote-{market.upper()}-{display_code.upper()}.json"


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "file"


def slugify(value: str, default: str = "topic") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or default


def markdown_bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def read_text_excerpt(path: Path, max_chars: int = 800) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:max_chars].strip()


def _http_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    config = load_config()
    headers = {
        "User-Agent": os.environ.get("STOCKANY_USER_AGENT", config["http"]["user_agent"]),
        "Accept-Encoding": "gzip, deflate",
    }
    if extra:
        headers.update(extra)
    return headers


def fetch_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> bytes:
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(url, headers=_http_headers(headers))
    timeout = load_config()["http"]["timeout_seconds"]
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            encoding = (response.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip":
                return gzip.decompress(payload)
            return payload
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc}") from exc


def fetch_text(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    encoding: str = "utf-8",
) -> str:
    return fetch_bytes(url, headers=headers, params=params).decode(encoding, errors="ignore")


def fetch_json(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    return json.loads(fetch_text(url, headers=headers, params=params))


def write_bytes(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def load_config() -> dict[str, Any]:
    ensure_runtime_layout()
    payload = load_json(CONFIG_PATH, default=None)
    if payload is None:
        dump_json(CONFIG_PATH, DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    if "http" not in payload:
        payload["http"] = DEFAULT_CONFIG["http"]
    return payload


def merge_unique_dicts(items: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    merged: list[dict[str, Any]] = []
    for item in items:
        key = tuple(item.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
