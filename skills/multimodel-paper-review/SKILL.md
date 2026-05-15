---
name: multimodel-paper-review
description: Review academic papers by extracting PDF or text, collecting independent critiques from Claude Code and Gemini, optionally running a supervisor/adversarial stress-test pass, and synthesizing a concise Codex reviewer report in ACM Multimedia or similar conference formats. Use when the user asks to review, critique, score, or write peer-review comments for a paper, especially when they mention shengao, review, PDF, ACM MM, strengths/weaknesses/rating, Claude Code, Gemini, CCB, multi-agent review, supervisor review, pre-submission audit, adversarial review, or integrate ARIS/Supervisor-Skills style review loops.
---

# Multimodel Paper Review

## Overview

Use this skill to run a disciplined paper-review workflow: Codex reads the paper, Claude Code and Gemini produce independent reviewer notes, an optional supervisor pass stress-tests the notes, then Codex synthesizes a final review grounded in the paper text and the requested venue format.

## Workflow

1. Identify the paper path or text, venue, target review form, and desired length. If the venue is ACM Multimedia, load `references/acmmm_review_template.md` before writing the final review.
2. Choose a profile:
   - `peer-review`: default conference-review surface.
   - `supervisor`: pre-submission audit of claims, narrative, evidence, figures, and writing.
   - `adversarial`: harsher score calibration and overclaim detection.
3. Run `scripts/multimodel_paper_review.py` to extract paper text and request independent notes from Claude Code and Gemini.
4. Use `--stress-test` when the user wants ARIS-like reviewer pressure or Supervisor-Skills-like pre-submission rigor. It asks the external models to audit the reviewer notes for unsupported criticisms, missed severe issues, disagreements, and score consistency.
5. Read the generated artifacts, especially `paper_text.txt`, `combined_notes.md`, `review_state.json`, `MANIFEST.md`, and `codex_synthesis_prompt.md`.
6. Produce the final review as Codex. Do not mechanically average the other models. Resolve disagreements by checking the paper text and favoring concrete evidence.
7. Report provider failures explicitly but continue with the available evidence.

## Quick Start

PowerShell:

```powershell
python "$env:USERPROFILE\.codex\skills\multimodel-paper-review\scripts\multimodel_paper_review.py" `
  --paper "C:\path\to\paper.pdf" `
  --out-dir "$env:TEMP\paper_review" `
  --venue acmmm `
  --profile supervisor `
  --stress-test
```

Use `--skip-claude` or `--skip-gemini` only when that provider is unavailable or the user asks for a narrower review. Use `--resume` to reuse existing artifacts in the output directory after an interruption. Use `--max-chars` and `--stress-max-chars` to adjust how much extracted paper text each external model receives.

## Provider Notes

- Claude Code: the script invokes `claude --bare --print --output-format text` and loads local values from `~/.claude/settings.json` into the subprocess environment when present.
- Gemini: the script uses `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `~/.gemini/settings.json`. It tries a fallback model list because Gemini preview and flash endpoints can have transient quota or availability failures.
- Never commit or paste local API keys. The script records outputs and sanitized error messages only.

## Integrated Patterns

Read `references/integration_patterns.md` when changing the workflow. The current integration keeps the pipeline lightweight while borrowing three practical ideas from multi-agent research tooling: artifact-first review logs, resumable state, and optional supervisor/adversarial pressure.

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
- `review_state.json`: resumable state and provider status.
- `MANIFEST.md`: artifact inventory.
- `claude_stress_test.md` and `gemini_stress_test.md`: optional stress-test notes when enabled.
