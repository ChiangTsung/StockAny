# Workflows

## Parse User Chat

- Run `./stockany intake parse-message --message "..."`.
- If the message contains new substantive investment content, check `./stockany charter show` before giving the next meaningful reply.
- If there are recent but unmerged principles in play, also check `./stockany charter candidates list`.
- If `intent_type` is `record_trade` or `create_dossier`, show the parsed result and confirm before mutation.
- If `charter_signal` is present, preserve it for the next daily review even if no mutation happens.
- If `security_matches` has multiple rows, ask the user to pick one instead of auto-guessing.

## Resolve A Security

- Run `./stockany security resolve --query "贵州茅台"` for Chinese names, pinyin, or 6-digit codes.
- Use `--market CN` to bias toward A-shares when the query is ambiguous.
- Use the returned `display_code` in later commands.

## Create A Dossier

- Run `./stockany dossier create --ticker TICKER --thesis "..."`.
- Run `./stockany dossier create --query "贵州茅台" --thesis "..."` for A-shares by name or pinyin.
- Before turning the new dossier into an actionable recommendation, check `./stockany charter show` and mention whether the idea fits the current charter or whether the charter is still unset.
- Follow with `./stockany advice run --ticker TICKER --event-type dossier_created` when the user asks for an opinion.
- Treat the output as a briefing packet. The surrounding Codex/OpenClaw session should produce the final prose recommendation.
- Keep the original `research/<ticker>/` files intact.

## Record A Trade

- Run `./stockany portfolio record-trade --ticker TICKER --side buy|sell --quantity N --price P --traded-at ISO_DATE`.
- For A-shares, `TICKER` should be the `display_code` such as `600519.SH`.
- Use the original message as `--source-message` when available.
- Before confirming the trade in prose, check `./stockany charter show` and `./stockany charter candidates list`.
- If there is an active charter, call out any sizing, add, trim, exit, or risk conflict. If there is no active charter, say the advice is less personalized.
- Follow with `./stockany advice run --ticker TICKER --event-type trade_changed`.
- Use the returned evidence and questions to write the final recommendation in chat.

## Sync Filings

- Run `./stockany filings sync --ticker TICKER` for one stock.
- Run `./stockany filings sync --all-active` for a full refresh.
- Treat documents in `inbox/pending-review/` as review tasks, not automatic thesis changes.
- US filings come from `SEC`; A-share disclosures come from `CNInfo` through `AKShare`.

## Run The Daily Charter Review

- Save same-day chat or notes into `state/journal/YYYY-MM-DD.jsonl` using `python3 scripts/journal.py append --message "..."` only if you specifically need the journal helper directly.
- Run `./stockany review daily`.
- Present the resulting candidate list and ask which items should merge into the charter.
- The daily review groups pending documents and positions by market/currency.
- Do not treat daily review as the only time to check the charter; chat-time guidance should already be charter-aware.

## Give Advice

- Before final user-facing advice, check `./stockany charter show`.
- If relevant, also check `./stockany charter candidates list` so recent but unmerged principles are not ignored.
- Use `./stockany advice run --ticker TICKER --event-type dossier_created|trade_changed|daily_review`.
- In the final prose, explicitly state one of:
  - `aligned with current charter`
  - `conflicts with current charter`
  - `no active charter yet`

## Manage The Charter

- Show the current charter with `./stockany charter show`.
- Read the canonical charter markdown from `assets/charter-active.md` when you need the actual current charter text.
- Use `assets/charter-template.md` as a scaffold and `assets/charter-active-v*.md` as version history.
- Set a full charter from markdown with `./stockany charter set --file assets/charter-active.md` or another charter markdown file.
- List candidate rules with `./stockany charter candidates list`.
- Review a candidate with `./stockany charter candidates review --candidate-id N`.
- Merge confirmed candidates with `./stockany charter candidates merge --candidate-ids N ...`.
- After `charter set` or candidate merge, the skill syncs the latest charter back into `assets/charter-active.md`.
