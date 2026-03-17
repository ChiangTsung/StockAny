# StockAny

StockAny is a CLI-first investing research skill for Codex and OpenClaw. It is built for a conversation-driven workflow where each topic owns one canonical investment report, while the CLI manages long-lived state, materials, memory, and archival.

StockAny 是一个面向 Codex 和 OpenClaw 的 CLI-first 投研 skill。它服务于“连续对话驱动一份主题投资报告”的工作流，由 CLI 承担长期状态、资料、记忆和归档管理，skill 只保留一层很薄的对话适配。

## Highlights

- `CLI-first runtime`: durable state lives in the CLI, not in the chat layer.
- `Thin skill adapter`: the skill receives prepared context and returns reply plus report patch.
- `Topic-centric reports`: each topic keeps one canonical `report.md`.
- `Analysis-first workflow`: once local filings and core materials are sufficient, the runtime shifts from collecting to analysis.
- `Versioned memory`: both `charter` and `evaluation` are versioned, inspectable, and switchable from the CLI.
- `Topic-contained materials`: issuer snapshots and copied filings are stored inside each topic workspace.

- `CLI-first 运行时`：长期状态由 CLI 托管，不依赖聊天层记忆。
- `薄 skill 适配层`：skill 只消费准备好的上下文，并返回回复与报告 patch。
- `主题化报告`：每个 topic 只维护一份 canonical `report.md`。
- `analysis-first 工作流`：本地财报和核心资料齐备后，运行时会显式转向分析与回答，而不是继续扩展式搜集。
- `版本化记忆`：`charter` 和 `evaluation` 都支持历史查看、切换和回滚。
- `主题自包含资料`：issuer 快照、行情和复制后的 filings 都保存在 topic 自己的工作区里。

## Architecture

The current branch implements a CLI-first architecture with four layers:

1. `Collector Layer`
   Low-level primitives for `security`, `market`, `filings`, `portfolio`, and dossier workflows.
2. `Topic Runtime Layer`
   Topic lifecycle, deduplication, report persistence, material linking, archival, and turn logs.
3. `Memory Layer`
   Versioned `charter` and `evaluation`, including active-file switching and compiled runtime state.
4. `Skill Adapter Layer`
   A stable `prepare / commit` contract for chat models.

当前分支实现的是一个四层 CLI-first 架构：

1. `Collector Layer`
   保留 `security`、`market`、`filings`、`portfolio`、dossier 等底层采集原语。
2. `Topic Runtime Layer`
   负责 topic 生命周期、去重、报告落盘、资料挂载、归档和 turn log。
3. `Memory Layer`
   负责 `charter` 与 `evaluation` 的版本化、激活文件切换和运行态缓存。
4. `Skill Adapter Layer`
   对模型暴露稳定的 `prepare / commit` 协议。

## Core Workflow

The main workflow is:

```text
user dialogue -> topic turn prepare -> model reply + report patch -> topic turn commit
```

`prepare` returns the current report, evaluation, charter, materials, and runtime guidance. `commit` writes the updated report, records a turn log, and applies any accepted charter or evaluation signals.

主工作流固定为：

```text
用户对话 -> topic turn prepare -> 模型回复 + report patch -> topic turn commit
```

`prepare` 会返回当前报告、evaluation、charter、materials 和运行时 guidance；`commit` 则负责写回报告、记录 turn log，并在满足规则时吸收 charter / evaluation 信号。

## Analysis-First Behavior

StockAny is intentionally not a “keep searching forever” system.

- Topic preparation reuses local materials first.
- It refreshes market snapshots and copies locally reviewed documents into the topic workspace.
- It does not automatically run broad filing sync during the normal topic turn workflow.
- `prepare` now returns `research_mode` and `research_state`.
- When `research_mode=analysis`, the model should focus on analyzing the existing report and answering the user instead of continuing broad material collection.

StockAny 的默认行为不是“无限继续搜资料”。

- topic 准备阶段优先复用本地已有资料。
- 它会刷新行情快照，并把本地已审阅文档复制进当前 topic。
- 在正常的 topic turn 主流程里，不会自动触发大范围 filing sync。
- `prepare` 现在会显式返回 `research_mode` 和 `research_state`。
- 当 `research_mode=analysis` 时，模型应优先分析现有报告、回答问题并更新结论，而不是继续扩展式搜集。

## Topic Model

A topic is the only long-lived working unit. Supported types:

- `security`
- `series`
- `basket`
- `theme`

Each topic owns:

- one canonical `report.md`
- one `report.meta.json`
- one `context.json`
- one `turns.jsonl`
- one `materials/manifest.json`
- one local `issuers/<display_code>/` snapshot area

`topic` 是唯一的长期工作单元，支持以下类型：

- `security`
- `series`
- `basket`
- `theme`

每个 topic 都拥有：

- 一份 canonical `report.md`
- 一份 `report.meta.json`
- 一份 `context.json`
- 一份 `turns.jsonl`
- 一份 `materials/manifest.json`
- 一套本地 `issuers/<display_code>/` 快照目录

## Memory

Two memories are managed by the CLI:

- `charter`
  Investment discipline, sizing, exits, and risk rules.
- `evaluation`
  Reporting preferences, preferred metrics, sector-specific emphasis, and default presentation habits.

Authoritative active files:

- `assets/charter-active.md`
- `assets/evaluation-active.md`

Both memories support history and switching:

- `./stockany charter history`
- `./stockany charter switch --version N`
- `./stockany evaluation history`
- `./stockany evaluation switch --version N`

CLI 管理两套长期记忆：

- `charter`
  投资纪律、仓位、退出和风险约束。
- `evaluation`
  报告偏好、行业指标重点、展示方式和默认补充规则。

当前权威 active 文件位于：

- `assets/charter-active.md`
- `assets/evaluation-active.md`

两者都支持查看历史与切换：

- `./stockany charter history`
- `./stockany charter switch --version N`
- `./stockany evaluation history`
- `./stockany evaluation switch --version N`

## Topic-Contained Materials

Issuer data is no longer treated as a global runtime workspace. Instead, each topic keeps its own snapshot:

```text
research/topics/<topic-slug>/
  report.md
  report.meta.json
  context.json
  turns.jsonl
  materials/manifest.json
  issuers/<display_code>/
    issuer.json
    market_snapshot.json
    filings/
    notes/
    analysis/
```

This makes each topic easier to archive, export, replay, and inspect without depending on a shared issuer directory.

issuer 数据不再以全局运行时目录为主，而是随 topic 自包含保存：

```text
research/topics/<topic-slug>/
  report.md
  report.meta.json
  context.json
  turns.jsonl
  materials/manifest.json
  issuers/<display_code>/
    issuer.json
    market_snapshot.json
    filings/
    notes/
    analysis/
```

这样每个 topic 都更容易归档、导出、复盘，也不会依赖一个共享的 issuer 根目录。

## CLI Commands

High-level topic commands:

```bash
./stockany topic open --query "光模块"
./stockany topic show --topic-id topic_光模块
./stockany topic archive --topic-id topic_光模块
./stockany topic turn prepare --topic-query "COHR" --message "我想看 COHR，这次重点是光模块投资逻辑"
./stockany topic turn commit --topic-id topic_光模块 --commit-json payload.json
```

Memory commands:

```bash
./stockany charter show
./stockany charter history
./stockany charter switch --version 2
./stockany evaluation show
./stockany evaluation history
./stockany evaluation switch --version 3
./stockany evaluation rebuild
```

## Repository Contents

This repository is the publishable skill package. Durable personal runtime state such as `research/`, `state/stockany.db`, and local inbox items are intentionally excluded from git.

这个仓库是可发布的 skill 包。像 `research/`、`state/stockany.db`、本地 inbox 之类的个人运行态内容，设计上不会进入 git。

## Install

### Codex

```bash
cp -R stockany ~/.codex/skills/stockany
```

### OpenClaw

Install it as a local AgentSkills-compatible directory and let OpenClaw load `SKILL.md`.

## Dependencies

```bash
python3 -m pip install --user -r requirements.txt
```

## License

This project is licensed under [Apache-2.0](LICENSE).
