---
name: multimodel-paper-review
description: Review academic papers by extracting PDF or text, collecting independent critiques from Claude Code and Gemini, and synthesizing a concise Codex reviewer report in ACM Multimedia or similar conference formats. Use when the user asks to review, critique, score, or write peer-review comments for a paper, especially when they mention shengao, review, PDF, ACM MM, strengths/weaknesses/rating, Claude Code, Gemini, CCB, or multi-agent review.
---

# Multimodel Paper Review

## Overview

Use this skill to run a disciplined paper-review workflow: Codex reads the paper, Claude Code and Gemini produce independent reviewer notes, then Codex synthesizes a final review grounded in the paper text and the requested venue format.

## Workflow

1. Identify the paper path or text, venue, target review form, and desired length. If the venue is ACM Multimedia, load `references/acmmm_review_template.md` before writing the final review.
2. Run `scripts/multimodel_paper_review.py` to extract paper text and request independent notes from Claude Code and Gemini.
3. Read the generated artifacts, especially `paper_text.txt`, `claude_review.md`, `gemini_review.md`, and `codex_synthesis_prompt.md`.
4. Produce the final review as Codex. Do not mechanically average the other models. Resolve disagreements by checking the paper text and favoring concrete evidence.
5. Report provider failures explicitly but continue with the available evidence.

## Quick Start

PowerShell:

```powershell
python "$env:USERPROFILE\.codex\skills\multimodel-paper-review\scripts\multimodel_paper_review.py" `
  --paper "C:\path\to\paper.pdf" `
  --out-dir "$env:TEMP\paper_review" `
  --venue acmmm
```

Use `--skip-claude` or `--skip-gemini` only when that provider is unavailable or the user asks for a narrower review. Use `--max-chars` to adjust how much extracted paper text each external model receives.

## Provider Notes

- Claude Code: the script invokes `claude --bare --print --output-format text` and loads local values from `~/.claude/settings.json` into the subprocess environment when present.
- Gemini: the script uses `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `~/.gemini/settings.json`. It tries a fallback model list because Gemini preview and flash endpoints can have transient quota or availability failures.
- Never commit or paste local API keys. The script records outputs and sanitized error messages only.

## Review Standards

- Treat the paper text as the source of truth. Mark uncertain claims as uncertain instead of inventing missing results.
- Separate novelty, technical quality, empirical support, presentation, and venue fit.
- For ACM Multimedia, use the exact required field names from `references/acmmm_review_template.md`.
- Keep final reviews concise when the user asks for a submission-ready form. Prefer clear numbered points over long prose.
- When scoring, make the score match the written evidence. If the paper claims SOTA but misses strong baselines, has tiny gains, or lacks statistical support, say so plainly.

## Outputs

The script writes:

- `paper_text.txt`: extracted paper text.
- `paper_meta.json`: extraction and provider status.
- `claude_review.md`: Claude Code notes or a failure note.
- `gemini_review.md`: Gemini notes or a failure note.
- `combined_notes.md`: compact combined notes for inspection.
- `codex_synthesis_prompt.md`: ready-to-use prompt for Codex to write the final review.
