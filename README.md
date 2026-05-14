# Multimodel Paper Review Skill

Codex skill for academic paper reviewing with Codex synthesis plus independent Claude Code and Gemini notes.

The skill extracts a PDF or text paper, asks Claude Code and Gemini for separate reviewer critiques, and writes artifacts that Codex can synthesize into an ACM Multimedia-style review.

## Install

Install this skill into Codex from GitHub:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo kenchikuliu/multimodel-paper-review-skill `
  --path skills/multimodel-paper-review
```

Restart Codex after installation.

## Use

Ask Codex:

```text
Use $multimodel-paper-review to review C:\path\paper.pdf in ACM MM format.
```

Or run the bundled helper directly:

```powershell
python "$env:USERPROFILE\.codex\skills\multimodel-paper-review\scripts\multimodel_paper_review.py" `
  --paper "C:\path\paper.pdf" `
  --out-dir "$env:TEMP\paper_review" `
  --venue acmmm
```

## Local Provider Configuration

- Claude Code: requires `claude` on PATH. The script reads `~/.claude/settings.json` when available and applies those values only to the subprocess environment.
- Gemini: uses `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `~/.gemini/settings.json`.

No API keys or local settings are included in this repository.
