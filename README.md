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
