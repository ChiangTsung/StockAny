# Schemas

## Intake Parse Output

```json
{
  "intent_type": "create_dossier | record_trade | ask_advice | add_note | unknown",
  "ticker": "600519.SH",
  "security_matches": [
    {
      "market": "CN",
      "exchange": "SSE",
      "symbol": "600519",
      "display_code": "600519.SH",
      "company_name_zh": "贵州茅台",
      "name_pinyin": "guizhoumaotai",
      "name_pinyin_abbr": "gzmt",
      "currency": "CNY",
      "confidence": 0.98
    }
  ],
  "trade": {
    "side": "buy",
    "quantity": 20.0,
    "price": 1680.0
  },
  "thesis_summary": "高端白酒龙头，品牌与渠道壁垒极强",
  "charter_signal": {
    "candidate_kind": "sizing",
    "candidate_text": "单票最好别超过 15%",
    "confidence": 0.72
  },
  "requested_action": "record_trade",
  "confidence": 0.86,
  "needs_confirmation": true
}
```

## Daily Review JSON

```json
{
  "review_date": "2026-03-10",
  "new_charter_candidates": [],
  "candidate_groups": {},
  "document_alerts": [
    {
      "ticker": "600519.SH",
      "market": "CN",
      "exchange": "SSE",
      "title": "贵州茅台2024年年度报告",
      "document_subtype": "annual_report",
      "filed_at": "2025-04-03",
      "source_platform": "cninfo"
    }
  ],
  "position_alerts": [
    {
      "market": "US",
      "currency": "USD",
      "exchange": "NASDAQ",
      "ticker": "META",
      "message": "META 20 shares at avg cost 485.0"
    }
  ],
  "open_questions": []
}
```

## Charter Compile Output

```json
{
  "investment_goals": [],
  "allowed_styles": [],
  "position_sizing_rules": [],
  "ban_conditions": [],
  "add_conditions": [],
  "trim_conditions": [],
  "exit_conditions": [],
  "risk_limits": [],
  "experience_patterns": [],
  "reflection_rules": []
}
```

## Advice Metadata

```json
{
  "ticker": "600519.SH",
  "display_code": "600519.SH",
  "market": "CN",
  "exchange": "SSE",
  "currency": "CNY",
  "event_type": "trade_changed",
  "briefing_mode": "agent-native",
  "suggested_stance": "cautious",
  "risk_level": "elevated",
  "charter_status": "active",
  "charter_version": 13,
  "charter_source_file": "/abs/path/assets/charter-active.md",
  "charter_versioned_source_file": "/abs/path/assets/charter-active-v13.md",
  "charter_full_markdown": "# StockAny Charter\\n...",
  "compiled_rules_json": {
    "position_sizing_rules": [],
    "risk_limits": []
  },
  "charter_conflicts": [],
  "evidence_refs": [],
  "followup_questions": [],
  "suggested_action": "复核是否符合仓位纪律"
}
```

- `charter_full_markdown` is required whenever a non-empty charter exists.
- The agent should treat `charter_full_markdown` as the primary charter context and `compiled_rules_json` as a convenience index only.
