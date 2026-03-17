# CLI-First, Thin-Skill Architecture

## Goal

Refactor StockAny from a skill-centric tool bundle into a CLI-first product with a thin skill adapter.

The CLI becomes the durable system of record for:

- state
- workflows
- report iteration
- charter lifecycle
- research preference memory
- topic dedupe and archival

The skill becomes a lightweight chat adapter that:

- forwards the latest user turn into the CLI
- renders CLI output back to the user
- only asks follow-up questions when the CLI explicitly says required inputs are missing

This split should improve stability, reduce repeated prompt assembly, and lower token usage.

## Product Mode

The target product mode is:

1. collect information
2. enter a continuous chat loop
3. use the chat loop to generate and revise an investment report around a topic

This is not a one-shot Q and A assistant. The chat session is a report-building session with durable state.

## Core Requirements

### 1. Existing data collection stays intact

Keep current security, market, filings, dossier, and portfolio collection capabilities as reusable CLI primitives.

Examples:

- market refresh
- filings sync
- dossier create and show
- security resolution
- portfolio bookkeeping

### 2. Charter management moves to the CLI

The CLI owns the full charter lifecycle:

- detect first run or missing charter
- bootstrap a starter charter from template plus guided supplementation
- save every charter revision with history
- show current charter
- list charter history
- switch active charter version
- apply silent iterative improvements from chat context with versioned auditability

Silent updates must still be reversible. "Silent" means the user does not need to manually manage files for normal iteration, not that the system loses version history.

### 3. Chat drives an investment report

The main chat objective is to produce and repeatedly revise a topic report.

A topic can be:

- one security
- a series
- a basket or thematic group

Every relevant turn should update the canonical report state. The assistant reply should be derived from the current report state instead of being a disconnected one-off answer.

### 4. Chat equals output

During normal conversation, the system should silently do the following in the background:

- update the report draft
- refresh or attach missing supporting materials
- refine charter memory when the turn reveals stable investing preferences
- refine research preference memory when the turn reveals preferred metrics or presentation patterns

The user should feel that "talking" and "editing the report" are the same workflow.

### 5. CLI-level archive and dedupe

The CLI should detect similar topics and avoid duplicate search and collection work.

Required behavior:

- detect whether a new topic overlaps an existing security, theme, or basket
- suggest reusing an existing topic when overlap is high
- reuse already collected materials when possible
- archive stale topics without losing report history or source links

### 6. Root-level research preference memory

Add a CLI-managed preference markdown file at the repository root, above all topic files.

This file records user-specific research preferences, for example:

- what types of securities need extra checks
- what extra operating or financial data should be displayed
- what sector-specific forward metrics matter
- what style of report structure is preferred

Examples of stored preferences:

- growth pharma: emphasize NTM PS, revenue growth, quality of growth, pipeline maturity
- tech manufacturing: emphasize segment revenue, utilization, backlog, capex intensity

The markdown file is human-readable and user-owned. The CLI may keep a compiled cache in structured form for low-token runtime use.

## Architecture Split

### CLI responsibilities

The CLI should own:

- topic identity and lifecycle
- material collection and reuse
- persistent report files
- report revision history
- charter history and activation
- preference memory updates
- dedupe and archival logic
- compact JSON payloads for the skill

### Thin skill responsibilities

The skill should only:

- translate the latest user turn into one CLI call
- inspect the CLI response
- ask a narrow follow-up when the CLI requires missing input
- return the report-backed response markdown

The skill should not be the primary keeper of:

- report context
- charter state
- preference memory
- source-material retrieval rules
- topic dedupe logic

## Domain Objects

### Security dossier

Keep the existing dossier concept for issuer-level facts and collected data.

This remains useful even when a topic is broader than one security.

### Topic

A topic is the main working unit for the report loop.

Each topic should have:

- `topic_id`
- `title`
- `topic_type` such as `security`, `series`, `basket`, or `theme`
- canonical member securities if any
- alias names and normalized query keys
- lifecycle status such as `active`, `archived`, or `merged`
- a stable workspace path

### Report

Each topic owns a canonical report that is incrementally revised.

The report should support:

- full markdown body
- section-level revision
- a short working summary for low-token reload
- revision history
- optional user-facing diff summary for each turn

### Charter

The charter becomes a versioned CLI object, not just a markdown file plus helper tables.

Recommended states:

- `unset`
- `draft`
- `active`
- `superseded`

### Research preference profile

This is separate from the charter.

The charter answers:

- how the user wants to invest

The research preference profile answers:

- what the user wants to inspect and highlight when building reports

### Material item

A material item is any fetched or derived input that can support a report:

- filing
- quote snapshot
- valuation snapshot
- segment data note
- management note
- peer comparison note

Each item should be linkable to one or more topics.

## Storage Layout

Recommended durable layout:

```text
evaluation.md
research/
  issuers/
    META/
    600519.SH/
  topics/
    <topic-slug>/
      report.md
      report.meta.json
      context.json
      turns.jsonl
      materials/
      exports/
assets/
  charter-active.md
  charter-active-v*.md
state/
  stockany.db
  cache/
  reports/
```

Notes:

- `evaluation.md` is the root-level human-readable preference file.
- issuer dossiers move under `research/issuers/` to avoid collision with topic workspaces.
- topic workspaces become the canonical home for report iteration.

## Database Additions

Current tables cover securities, dossiers, trades, documents, advice runs, and charter candidates.

Add topic-centric tables:

- `topics`
- `topic_members`
- `topic_aliases`
- `topic_turns`
- `topic_reports`
- `topic_material_links`
- `topic_similarity_links`
- `research_profile_revisions`

Minimum fields by table:

- `topics`: identity, title, type, status, summary, workspace path, active report revision
- `topic_members`: topic to security linkage with role and confidence
- `topic_turns`: user turn, parsed intent, applied actions, created report revision
- `topic_reports`: revision id, markdown body, summary, diff note, created at
- `topic_material_links`: topic id, source object type, source object id, relevance note
- `topic_similarity_links`: source topic, target topic, similarity score, resolution
- `research_profile_revisions`: markdown snapshot, compiled json, created at

## Command Surface

Keep the existing low-level commands. Add a topic-first layer above them.

Recommended new command families:

### `stockany topic open`

Input:

- free-form topic title or security query

Behavior:

- resolve whether to create, reuse, or merge into an existing topic
- return topic metadata and dedupe hints

### `stockany topic turn`

This should be the main skill-facing entrypoint.

Input:

- topic id or raw topic query
- latest user message

Behavior:

- parse intent
- load current topic context
- check charter state
- check research preference profile
- decide whether more materials are needed
- update the report
- optionally update charter or profile memory
- return a compact response payload

Suggested payload shape:

```json
{
  "topic_id": "topic_nvda_supply_chain",
  "status": "ok",
  "stage": "collecting",
  "report_path": "/abs/path/research/topics/topic_nvda_supply_chain/report.md",
  "report_updated": true,
  "charter_updated": false,
  "profile_updated": true,
  "response_markdown": "current user-facing answer",
  "report_summary": "low-token working summary",
  "needs_user_input": [],
  "dedupe": {
    "matched_topic_id": "topic_nvda",
    "similarity": 0.84,
    "action": "reuse_materials"
  }
}
```

### `stockany topic show`

Return:

- topic metadata
- current report
- recent turns
- linked materials
- related topics

### `stockany topic archive`

Archive the topic while keeping its report history and material links intact.

### `stockany charter history`

List all charter versions with created time, status, and reason.

### `stockany charter switch --version N`

Activate an older charter revision.

### `stockany profile show`

Show the current `evaluation.md` plus compiled runtime summary.

### `stockany profile rebuild`

Recompile the root preference markdown into structured runtime form.

## Conversation Contract Between Skill And CLI

The thin skill should prefer one command:

```text
./stockany topic turn ...
```

The CLI response should tell the skill what to do next.

Expected cases:

- `response_markdown` present: return it directly
- `needs_user_input` present: ask only those missing questions
- `dedupe.action = reuse_existing_topic`: tell the user we continued the existing topic
- `stage = collecting`: explain that the report has already been updated with newly attached materials

This keeps prompt state small because the skill does not need to reconstruct the full topic history on every turn.

## Silent Update Rules

### Report

Every substantive turn may create a new report revision automatically.

### Charter

When the turn reveals stable investing behavior, the CLI may create a new charter revision automatically.

Recommended safeguards:

- record a machine-generated revision note
- preserve full history
- allow one-command rollback or version switch

### Research preference profile

When the turn reveals repeated data preferences, update `evaluation.md` and create a compiled revision cache.

This is a better place than the charter for sector-specific reporting habits.

## Similar Topic Handling

Similarity should be checked at two levels:

### security overlap

Examples:

- same ticker
- same issuer with alternate name
- same basket with small naming variations

### thematic overlap

Examples:

- "AI infrastructure"
- "NVIDIA supply chain"
- "HBM and AI memory"

Required behavior:

- avoid creating a brand-new topic when one already exists
- allow explicit branching when the user really wants a separate report
- reuse linked materials by reference rather than re-fetching everything

## Migration Direction

Recommended implementation order:

1. preserve current commands and database behavior
2. add topic tables and topic workspace storage
3. add `topic open`, `topic turn`, `topic show`, and `topic archive`
4. add charter history and version switching commands
5. add root-level `evaluation.md` plus compiled profile cache
6. move the skill to the single-entry `topic turn` contract
7. optionally move old commands behind the topic workflow where appropriate

This keeps the current data collectors usable while the higher-level report loop is built.

## Recommended Assumptions For This Branch

Unless new requirements contradict them, use these assumptions:

- the canonical user deliverable is a markdown investment report per topic
- the skill should not directly edit report files
- the CLI should own all durable state transitions
- charter and research preference profile are separate objects
- silent updates are acceptable only if versioned and reversible
- existing market and filings collectors remain low-level primitives, not the primary user workflow
