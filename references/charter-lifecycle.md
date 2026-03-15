# Charter Lifecycle

## Cold Start

- Start with `status = unset`.
- Allow dossier creation, trade recording, and advice generation without a charter.
- Add uncertainty language to advice when the charter is unset.
- The canonical charter file lives at `assets/charter-active.md`.

## Candidate Generation

- Extract candidates from chat, trade rationale, user reflections, and daily reviews.
- Store each candidate as `pending`.
- Write a note in `inbox/charter-candidates/` for human inspection.

## Merge Policy

- Merge only after explicit confirmation.
- If no active charter exists, merge into a `draft` charter.
- If an active charter exists, create a new version and mark the old one `superseded`.
- Preserve old versions for auditability.
- After `charter set` or merge, sync the latest markdown to `assets/charter-active.md`.
- Keep versioned snapshots in `assets/charter-active-v*.md`.
