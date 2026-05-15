# Integration Patterns

This skill uses a lightweight integration of ideas from:

- ARIS / Auto-claude-code-research-in-sleep: external reviewer loops, full raw review logging, resumable state, and adversarial review difficulty.
- Supervisor-Skills: pre-submission supervision as a separate lens from ordinary peer review.

Do not copy large checklist text from external projects into this skill. Keep this repository self-contained and license-clean.

## Applied Patterns

1. Artifact-first review
   - Save raw provider outputs, prompts, combined notes, and synthesis prompt.
   - Keep `MANIFEST.md` so the next agent can inspect what exists without guessing.

2. Resume-friendly state
   - Write `review_state.json` after every run.
   - Use `--resume` to reuse `paper_text.txt`, `claude_review.md`, `gemini_review.md`, and stress-test artifacts if present.

3. Review profiles
   - `peer-review`: normal conference review.
   - `supervisor`: checks claim/evidence mapping, narrative flow, experimental support, presentation, figures/tables, and writing.
   - `adversarial`: searches for overclaims, missing baselines, cherry-picking, inconsistent scores, and unsupported criticisms.

4. Stress-test pass
   - Use `--stress-test` after first-round reviews.
   - Ask reviewers to inspect reviewer notes, not to rewrite the review.
   - Codex should use stress-test notes to calibrate the final review and remove weak criticisms.

## Synthesis Rule

Final synthesis remains Codex's responsibility. Claude and Gemini are independent signals. If they disagree, check the paper text and record uncertainty rather than averaging scores.
