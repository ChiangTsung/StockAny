# Troubleshooting

## Yahoo Finance Refresh Fails

- Re-run `./stockany market refresh --ticker TICKER`.
- Inspect `state/cache/quote-US-TICKER.json` to see the last successful response.
- If Yahoo blocks the request, use cached data and tell the user the quote is stale.

## AKShare Fails

- Install dependencies with `python3 -m pip install --user -r requirements.txt`.
- Re-run `./stockany security resolve --query "600519"` to confirm the A-share security index can build.
- If the first A-share resolve is slow, let it finish once so `state/cache/cn-securities.json` can be reused.
- If AKShare quote APIs fail, keep the last cached quote and surface the error instead of deleting data.
- If the launcher itself fails, fall back to `python3 scripts/stockany.py ...` for direct debugging.

## SEC Sync Fails

- Check whether the ticker maps to a SEC CIK.
- Re-run the command for a single ticker to isolate the failure.
- If SEC blocks attachment downloads, keep the error in the sync result and continue with other tickers.

## CNInfo Sync Fails

- Re-run `./stockany filings sync --ticker 600519.SH`.
- If only one category fails, keep the sync partial result and continue with other categories.
- Expect A-share sync to store disclosure pages or announcement originals under `research/<display_code>/sources/`.

## Advice Output Feels Too Mechanical

- `./stockany advice run ...` intentionally produces a briefing packet, not the final model-written recommendation.
- Use the surrounding Codex or OpenClaw agent to turn the packet into final prose.
- If the packet is missing evidence, improve the underlying state first: sync filings, refresh quotes, or add more journal context.

## Parsing Misses A Trade

- Run the intake parser first and inspect the JSON output.
- If the price or quantity is ambiguous, ask the user a targeted follow-up instead of guessing.
- If the security query is ambiguous, run `./stockany security resolve ...` and ask the user to choose a candidate.

## Charter Candidate Noise

- Review the candidate note in `inbox/charter-candidates/`.
- Reject noisy candidates instead of merging them.
- Prefer fewer high-signal rules over many weak reflections.
