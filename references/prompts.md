# Prompting Notes

## Advice Style

- Use StockAny outputs as evidence packets, not as the final model layer.
- Explain the conclusion first.
- Tie every recommendation to evidence already stored in the skill state.
- Read the full charter markdown when it is present. Do not rely only on a few compiled rule lists or short excerpts.
- Mention missing personalization when the charter is unset.
- Ask for the smallest next decision that would sharpen future advice.
- Keep USD and CNY reasoning separate; do not compare positions across currencies without an explicit FX layer.
- When the security is `CN`, mention that filings and key announcements came from CNInfo or another official disclosure source.

## Candidate Extraction Style

- Prefer explicit user wording over paraphrasing.
- Classify by rule type: `style`, `sizing`, `ban`, `add`, `trim`, `exit`, `risk`, `reflection`.
- Keep one candidate per distinct principle.
- Preserve market-specific context when the user references A-share trading norms, boards, or code formats.
