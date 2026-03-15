---
name: stockany
description: Chat-first stock analysis, portfolio tracking, filing collection, and progressive investment-charter management for US equities and China A-shares. Use when Codex or OpenClaw needs to parse natural-language stock notes or trades, resolve US tickers or A-share codes and Chinese names, track dossiers and positions, sync Yahoo Finance, SEC, AKShare, and CNInfo data, run daily charter reviews, or export research snapshots from this folder as a self-contained skill.
---

# StockAny

Use this skill as the system itself. Keep state local in `state/`, keep source materials in `research/`, and favor chat-driven workflows over direct file edits. Use the agent you are currently running in for final reasoning; StockAny only prepares structured evidence, state, and review packets.

## Follow The Main Workflows

- Use `./stockany ...` as the default entrypoint for all normal skill operations.
- Do not narrate interpreter fallback or discuss `python` vs `python3` unless the launcher itself fails.
- Parse user chat with `./stockany intake parse-message --message "..."`.
- Resolve a security with `./stockany security resolve --query "贵州茅台"`.
- Create or update a tracked stock with `./stockany dossier create --ticker ... --thesis ...`.
- Record a trade with `./stockany portfolio record-trade ...`.
- Refresh market quotes with `./stockany market refresh --ticker ...` or `--all-active`.
- Sync filings with `./stockany filings sync --ticker ...` or `--all-active`.
- Generate an advice briefing with `./stockany advice run --ticker ... --event-type ...`, then use your current agent model to turn that briefing into final user-facing advice.
- Run the daily charter review with `./stockany review daily`.
- Review or merge charter candidates with `./stockany charter candidates ...`.

## Check The Charter At Decision Time

- When a session receives new substantive chat content about a stock, a trade, risk, sizing, exit rules, or reflections, check the current charter before producing the next meaningful reply.
- Before giving portfolio-changing advice, check the current charter or the absence of one.
- Before recording or confirming a trade, compare the action against the active charter and pending charter candidates.
- Before recommending a new dossier as actionable, note whether it fits the user's current style, sizing, risk, and exit discipline.
- If the charter is `unset`, say that explicitly and frame the guidance as lower-confidence and less personalized.
- Pure data operations such as `security resolve`, `market refresh`, and `filings sync` do not need a charter check unless they are being turned into a recommendation.

## Preserve The Skill Contract

- Keep `research/<ticker>/` as durable research storage.
- Keep `state/stockany.db` as the structured source of truth.
- Keep the canonical charter markdown in `assets/charter-active.md`.
- Treat `assets/charter-active-v*.md` as versioned snapshots of merged or explicitly set charters.
- Keep `state/cache/cn-securities.json` as the A-share security-master cache.
- Keep `inbox/pending-review/` for new filings waiting for human review.
- Keep `inbox/charter-candidates/` for extracted charter candidate notes.
- Treat the investment charter as progressive. Do not block users on a missing charter.

## Use The Built-In References

- Read [references/workflows.md](references/workflows.md) for chat-to-command routing.
- Read [references/schemas.md](references/schemas.md) for CLI payload shapes.
- Read [references/charter-lifecycle.md](references/charter-lifecycle.md) for cold start and merge behavior.
- Read [references/prompts.md](references/prompts.md) when refining prompts or explanation style.
- Read [references/troubleshooting.md](references/troubleshooting.md) when network sync or parsing fails.

## Operate Safely

- Confirm trades before writing them.
- On `record_trade`, `advice run`, and trade-related chat, explicitly surface any charter conflict or say that no charter is active yet.
- Do not auto-merge charter candidates into an active charter.
- Do not auto-update thesis or charter based only on synced filings.
- Keep recommendations advisory only. Never imply automatic order execution.

## Market Rules

- Use `Yahoo Finance + SEC` for US securities.
- Use `AKShare + CNInfo` for China A-shares and Beijing exchange names.
- Show portfolio totals grouped by `market` and `currency`; do not add USD and CNY together.
- Prefer `display_code` in outputs: `META`, `600519.SH`, `000001.SZ`, `430047.BJ`.
