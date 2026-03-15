# StockAny

StockAny is a chat-first stock analysis skill for Codex and OpenClaw.

It supports:

- US equities with `Yahoo Finance + SEC`
- China A-shares with `AKShare + CNInfo`
- natural-language dossier creation and trade capture
- progressive investment-charter workflows
- filing sync, review packets, and advice briefings

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
./stockany charter show
./stockany security resolve --query META
./stockany security resolve --query 贵州茅台
./stockany advice run --ticker META --event-type trade_changed
```

## Dependencies

Install runtime dependencies with:

```bash
python3 -m pip install --user -r requirements.txt
```

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
