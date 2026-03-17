# StockAny

StockAny is a CLI-first stock analysis skill for Codex and OpenClaw, with US equities, A-shares, topic reports, filings, trades, and progressive investment-memory workflows.

It is designed for conversation-first investing workflows:

- build and maintain topic-centric investment reports from natural language
- record trades and positions through chat
- sync SEC, CNInfo, Yahoo Finance, and AKShare-backed data
- keep charter and evaluation memory versioned in the CLI

It supports:

- US equities with `Yahoo Finance + SEC`
- China A-shares with `AKShare + CNInfo`
- natural-language topic creation, dossier creation, and trade capture
- progressive investment-charter workflows
- evaluation preference memory in `assets/evaluation-active.md`
- filing sync, review packets, and topic report iteration

## Product Direction

This branch implements the CLI-first architecture for StockAny.

The core idea is:

- the CLI is the durable runtime
- the skill is a thin chat adapter
- the main workflow is `continuous topic dialogue -> one canonical investment report`

In practice, that means:

- each topic owns one canonical `report.md`
- the skill must always receive both the current investment report and the current evaluation preferences as explicit context
- charter and evaluation memory are versioned and managed by the CLI
- issuer data is stored inside each topic workspace under `research/topics/<topic>/issuers/<display_code>/`
- similar topics should be deduplicated or reused before collecting duplicate materials
- archiving happens at the CLI level without losing report history or topic-contained issuer snapshots

The target user experience is "chat equals output":

- users talk naturally about a security, basket, or theme
- the CLI silently keeps the report up to date
- the CLI silently refreshes or links topic materials
- stable investing rules update the charter
- stable reporting habits update the evaluation profile

## 中文需求摘要

这条分支的目标是把 StockAny 做成“独立 CLI + 薄 skill”的结构，重点解决稳定性和 token 消耗问题。

- 工作模式不是一次性问答，而是“先搜集资料，再连续对话，围绕一个主题持续生成和修改投资报告”。
- 一个 `topic` 只保留一份主投资报告，主题可以是单标的、系列、篮子或主题。
- `prepare / commit` 是 skill 与 CLI 的正式协议：
  - `prepare` 返回当前报告、evaluation、charter 和 topic materials
  - `commit` 提交当轮回复、报告 patch、charter/evaluation signals
- 投资宪章下沉到 CLI 管理，支持首次启动补充、历史版本查看和切换。
- `evaluation` 也由 CLI 维护，权威文件放在 `assets/evaluation-active.md`，用于记录用户偏好的资料补充与展示方式。
- issuer 数据不再作为全局主目录维护，而是跟随 topic 自包含存放，便于归档、复盘和导出。
- CLI 负责相似主题检测、资料复用和归档，尽量避免重复搜索和重复整理。

## What This Repo Contains

This repository is the clean, publishable skill package:

- `SKILL.md`
- `agents/openai.yaml`
- `assets/` templates
- `references/`
- `scripts/`
- `requirements.txt`
- `./stockany` launcher

It does not need to include your local research, inbox items, database, or personal charter snapshots.

## Install

### Codex

Copy this folder into your Codex skills directory as `stockany`.

Example:

```bash
cp -R stockany ~/.codex/skills/stockany
```

### OpenClaw

Install it as a local AgentSkills-compatible skill directory and let OpenClaw load `SKILL.md`.

## Usage

Use the launcher from the skill root:

```bash
./stockany topic open --query "AI infrastructure"
./stockany topic turn prepare --topic-query "AI infrastructure" --message "先搭报告骨架"
./stockany charter show
./stockany evaluation show
./stockany security resolve --query META
./stockany security resolve --query 贵州茅台
./stockany topic show --topic-id topic_ai_infrastructure
```

## Dependencies

Install runtime dependencies with:

```bash
python3 -m pip install --user -r requirements.txt
```

## License

This project is licensed under [Apache-2.0](LICENSE).

## Publish To GitHub

```bash
git add SKILL.md agents assets references scripts requirements.txt stockany README.md .gitignore state/config.json
git commit -m "Publish StockAny skill"
git remote add origin git@github.com:YOUR_NAME/stockany-skill.git
git push -u origin main
```

If you prefer HTTPS:

```bash
git remote add origin https://github.com/YOUR_NAME/stockany-skill.git
git push -u origin main
```
