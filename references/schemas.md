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

## Topic Turn Prepare Output

```json
{
  "status": "ok",
  "topic_id": "topic_ai_infrastructure",
  "topic_action": "created | reused | merged_into_existing",
  "topic_type": "theme",
  "report_path": "/abs/path/research/topics/ai-infrastructure/report.md",
  "report_markdown": "# AI infrastructure Investment Report\\n...",
  "report_summary": "AI infrastructure 的主题报告已初始化，等待对话逐步完善。",
  "evaluation_markdown": "# StockAny Evaluation\\n...",
  "evaluation_summary": "默认展示营收增速、利润率、现金流与估值框架。",
  "charter_status": "active | unset",
  "charter_markdown": "# StockAny Charter\\n...",
  "charter_summary": "单票仓位与退出纪律摘要",
  "materials": [],
  "dedupe": {
    "matched_topic_id": "",
    "similarity": 0.0,
    "action": "created_new_topic"
  },
  "needs_user_input": [],
  "reply_brief": {
    "topic_title": "AI infrastructure",
    "report_summary": "..."
  }
}
```

- `report_markdown` and `evaluation_markdown` are required.
- `charter_markdown` may be empty only when `charter_status = unset`.

## Topic Turn Commit Input

```json
{
  "user_message": "请把估值和风险写得更清楚",
  "assistant_reply_markdown": "我已经补上这两块。",
  "change_note": "补充估值与风险部分。",
  "report_patch": {
    "replace_sections": [
      {
        "section_id": "valuation_market_expectation",
        "markdown": "- 当前市场更愿意为确定性更高的龙头支付溢价。"
      }
    ],
    "append_evidence_refs": [
      "待补：云厂商 capex 指引"
    ],
    "updated_summary": "主题报告已补充估值与风险框架。"
  },
  "charter_signals": [],
  "evaluation_signals": []
}
```

## Topic Turn Commit Output

```json
{
  "topic_id": "topic_ai_infrastructure",
  "report_path": "/abs/path/research/topics/ai-infrastructure/report.md",
  "report_summary": "主题报告已补充估值与风险框架。",
  "changed_sections": [
    "valuation_market_expectation"
  ],
  "report_hash_before": "abc",
  "report_hash_after": "def",
  "charter_updated": false,
  "evaluation_updated": true
}
```
