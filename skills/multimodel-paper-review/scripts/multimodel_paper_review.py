#!/usr/bin/env python3
"""Prepare multi-model academic paper review artifacts.

The script extracts paper text, asks Claude Code and Gemini for independent
review notes, optionally runs a supervisor-style stress test, and writes
artifacts for Codex to synthesize into a final review. It never stores API
keys and continues when a provider is unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from typing import Any, Iterable


DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

VENUE_ALIASES = {"acmmm", "acm-mm", "acm multimedia"}

PROFILE_INSTRUCTIONS = {
    "peer-review": """
        Focus on the normal conference-review surface: novelty, technical soundness,
        empirical support, missing baselines or ablations, clarity, and venue fit.
    """,
    "supervisor": """
        Add a senior-advisor pre-submission audit. Check whether the paper's main
        claims map to method components and experiments, whether the narrative is
        self-contained, whether the experimental evidence supports the stated
        contribution, whether figures/tables/captions are reviewer-readable, and
        whether writing or formatting issues would distract reviewers.
    """,
    "adversarial": """
        Be adversarial. Look for overstated claims, cherry-picked comparisons,
        missing obvious baselines, unsupported conclusions, inconsistencies between
        abstract/method/experiments, and score inflation. Separate facts observed
        in the paper from hypotheses or suspicions.
    """,
}


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def find_pdftotext() -> str | None:
    candidates = [
        shutil.which("pdftotext"),
        r"C:\Program Files\Git\mingw64\bin\pdftotext.exe",
        r"C:\Program Files\poppler\Library\bin\pdftotext.exe",
    ]
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    return None


def extract_pdf_text(pdf_path: pathlib.Path, out_dir: pathlib.Path) -> tuple[str, str]:
    pdftotext = find_pdftotext()
    txt_path = out_dir / "paper_text.txt"
    if pdftotext:
        cmd = [pdftotext, "-layout", "-enc", "UTF-8", str(pdf_path), str(txt_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0 and txt_path.exists():
            text = read_text(txt_path)
            if len(text.strip()) > 200:
                return text, f"pdftotext:{pdftotext}"

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "PDF extraction failed: pdftotext unavailable and pypdf/PyPDF2 missing"
            ) from exc

    reader = PdfReader(str(pdf_path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            page_text = f"\n[Page {index} extraction failed: {exc}]\n"
        pages.append(f"\n\n--- Page {index} ---\n{page_text}")
    text = "\n".join(pages)
    write_text(txt_path, text)
    return text, "python-pdf-reader"


def extract_paper_text(paper_path: pathlib.Path, out_dir: pathlib.Path, resume: bool) -> tuple[str, str]:
    txt_path = out_dir / "paper_text.txt"
    if resume and txt_path.exists():
        return read_text(txt_path), "resume:paper_text.txt"

    suffix = paper_path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(paper_path, out_dir)
    if suffix in {".txt", ".md", ".tex"}:
        text = read_text(paper_path)
        write_text(txt_path, text)
        return text, f"text:{suffix}"
    raise ValueError(f"Unsupported paper format: {paper_path.suffix}")


def compact_text(text: str, max_chars: int) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.42)
    middle = int(max_chars * 0.28)
    tail = max_chars - head - middle
    mid_start = max(0, (len(text) // 2) - (middle // 2))
    omitted_1 = mid_start - head
    omitted_2 = len(text) - (mid_start + middle) - tail
    return (
        text[:head]
        + f"\n\n[... omitted {max(0, omitted_1)} characters from the middle of the paper ...]\n\n"
        + text[mid_start : mid_start + middle]
        + f"\n\n[... omitted {max(0, omitted_2)} characters before the ending ...]\n\n"
        + text[-tail:]
    )


def venue_name(venue: str) -> str:
    return "ACM Multimedia" if venue.lower() in VENUE_ALIASES else venue


def profile_block(profile: str) -> str:
    return textwrap.dedent(PROFILE_INSTRUCTIONS[profile]).strip()


def build_reviewer_prompt(paper_text: str, venue: str, profile: str) -> str:
    return textwrap.dedent(
        f"""
        You are an independent peer reviewer for {venue_name(venue)}.

        Review only the paper text below. Do not invent missing results. If a point is uncertain because the extracted text is incomplete, say so.

        Review profile:
        {profile_block(profile)}

        Return concise Markdown with these sections:
        - Paper summary
        - Strengths
        - Weaknesses
        - Technical concerns
        - Missing experiments or baselines
        - Presentation issues
        - Suggested scores for fit, technical quality, presentation, rating, confidence
        - Minimum changes that would most improve the paper

        Paper text:
        ```text
        {paper_text}
        ```
        """
    ).strip()


def build_stress_prompt(
    paper_text: str,
    venue: str,
    profile: str,
    claude: str,
    gemini: str,
) -> str:
    return textwrap.dedent(
        f"""
        You are a supervisor meta-reviewer for {venue_name(venue)}.

        Your job is not to write the final review. Your job is to stress-test the two reviewer notes below and protect the final Codex synthesis from weak reasoning.

        Review profile:
        {profile_block(profile)}

        Check the following:
        1. Unsupported criticisms: reviewer claims that are not clearly grounded in the paper text.
        2. Missed severe issues: likely critical weaknesses neither reviewer emphasized enough.
        3. Score consistency: whether the suggested scores match the written evidence.
        4. Disagreements: where Claude and Gemini disagree and what Codex should verify in the paper.
        5. Final synthesis guidance: what the final review should say, avoid, or hedge.

        Return concise Markdown with these sections:
        - Unsupported or overreaching reviewer claims
        - Missed severe issues
        - Disagreement matrix
        - Score calibration
        - Synthesis guidance

        Claude notes:
        ```markdown
        {claude}
        ```

        Gemini notes:
        ```markdown
        {gemini}
        ```

        Paper excerpt:
        ```text
        {paper_text}
        ```
        """
    ).strip()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def nested_find_api_key(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in {"apikey", "api_key", "gemini_api_key", "google_api_key"} and isinstance(value, str):
                if value.strip():
                    return value.strip()
            found = nested_find_api_key(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = nested_find_api_key(value)
            if found:
                return found
    return None


def redact(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def claude_env() -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    settings_path = pathlib.Path.home() / ".claude" / "settings.json"
    settings = load_json(settings_path)
    settings_env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    for key, value in settings_env.items():
        if isinstance(value, str) and value:
            env[key] = value
    if env.get("ANTHROPIC_AUTH_TOKEN") and not env.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = env["ANTHROPIC_AUTH_TOKEN"]
    model = env.get("ANTHROPIC_MODEL")
    return env, model


def run_claude(
    prompt: str,
    model: str | None,
    timeout: int,
    max_budget_usd: str | None,
) -> tuple[bool, str, str | None]:
    exe = shutil.which("claude")
    if not exe:
        return False, "Claude Code CLI not found on PATH.", None
    env, settings_model = claude_env()
    chosen_model = model or settings_model
    cmd = [exe, "--bare", "--print", "--output-format", "text"]
    if chosen_model:
        cmd.extend(["--model", chosen_model])
    if max_budget_usd:
        cmd.extend(["--max-budget-usd", max_budget_usd])
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except Exception as exc:
        return False, f"Claude invocation failed: {exc}", chosen_model
    secrets = [env.get("ANTHROPIC_AUTH_TOKEN", ""), env.get("ANTHROPIC_API_KEY", "")]
    output = result.stdout.strip()
    error = redact(result.stderr.strip(), secrets)
    if result.returncode != 0:
        message = error or output or f"Claude exited with code {result.returncode}."
        return False, message, chosen_model
    return True, output or "[Claude returned empty output.]", chosen_model


def gemini_api_key() -> str | None:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    settings_path = pathlib.Path.home() / ".gemini" / "settings.json"
    return nested_find_api_key(load_json(settings_path))


def run_gemini_sdk(prompt: str, model: str, api_key: str) -> str:
    from google import genai  # type: ignore

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    text = getattr(response, "text", None)
    if text:
        return text
    return str(response)


def run_gemini_rest(prompt: str, model: str, api_key: str, timeout: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise RuntimeError(f"Gemini returned no text: {json.dumps(data)[:1000]}")
    return text


def run_gemini(prompt: str, models: list[str], timeout: int) -> tuple[bool, str, str | None]:
    api_key = gemini_api_key()
    if not api_key:
        return False, "Gemini API key not found in GEMINI_API_KEY, GOOGLE_API_KEY, or ~/.gemini/settings.json.", None
    errors = []
    for model in models:
        try:
            try:
                return True, run_gemini_sdk(prompt, model, api_key).strip(), model
            except Exception as sdk_exc:
                try:
                    return True, run_gemini_rest(prompt, model, api_key, timeout).strip(), model
                except Exception as rest_exc:
                    errors.append(
                        f"{model}: SDK failed with {sdk_exc}; REST failed with {rest_exc}"
                    )
        except Exception as exc:
            errors.append(f"{model}: {exc}")
        time.sleep(1)
    return False, redact("\n".join(errors), [api_key]), None


def existing_or_call(
    path: pathlib.Path,
    resume: bool,
    skipped_message: str,
    call,
) -> tuple[bool, str, str | None, bool]:
    if resume and path.exists():
        return True, read_text(path), "resume", True
    if skipped_message:
        write_text(path, skipped_message)
        return False, skipped_message, None, False
    ok, output, model = call()
    write_text(path, output)
    return ok, output, model, False


def run_or_skip(path: pathlib.Path, resume: bool, skip: bool, skip_message: str, call) -> tuple[bool, str, str | None, bool]:
    if skip:
        if resume and path.exists():
            return False, read_text(path), "resume-skipped", True
        write_text(path, skip_message)
        return False, skip_message, None, False
    ok, output, model, resumed = existing_or_call(path, resume, "", call)
    if resumed:
        lowered = output.strip().lower()
        if lowered.startswith("skipped by"):
            return False, output, "resume-skipped", True
    return ok, output, model, resumed


def build_synthesis_prompt(
    venue: str,
    profile: str,
    paper_path: pathlib.Path,
    paper_text: str,
    claude: str,
    gemini: str,
    claude_stress: str | None,
    gemini_stress: str | None,
) -> str:
    template_note = (
        "Use references/acmmm_review_template.md field order."
        if venue.lower() in VENUE_ALIASES
        else f"Use the requested {venue} review format."
    )
    stress_block = ""
    if claude_stress or gemini_stress:
        stress_block = textwrap.dedent(
            f"""

            Supervisor stress-test notes:

            Claude stress test:
            ```markdown
            {claude_stress or "Not run."}
            ```

            Gemini stress test:
            ```markdown
            {gemini_stress or "Not run."}
            ```
            """
        )
    return textwrap.dedent(
        f"""
        Write the final peer review for:
        {paper_path}

        {template_note}

        Review profile: {profile}

        Instructions:
        - Use the paper text as the source of truth.
        - Use Claude and Gemini notes as independent signals, not as facts by themselves.
        - Use supervisor stress-test notes to avoid unsupported criticisms and score inflation.
        - Be concise and submission-ready.
        - Include concrete strengths, weaknesses, detailed review, fit, technical quality, presentation, rating, confidence, and best-paper recommendation when the form asks for them.
        - If provider notes disagree, resolve the issue by checking the paper text.
        - If evidence is missing because extraction was incomplete, hedge instead of inventing.

        Claude notes:
        ```markdown
        {claude}
        ```

        Gemini notes:
        ```markdown
        {gemini}
        ```
        {stress_block}

        Paper excerpt for verification:
        ```text
        {compact_text(paper_text, 18000)}
        ```
        """
    ).strip()


def artifact_table(out_dir: pathlib.Path, descriptions: dict[str, str]) -> str:
    rows = [
        "# Review Artifact Manifest",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| File | Description |",
        "|---|---|",
    ]
    for name, description in descriptions.items():
        path = out_dir / name
        if path.exists():
            rows.append(f"| `{name}` | {description} |")
    return "\n".join(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare multi-model paper review artifacts.")
    parser.add_argument("--paper", required=True, help="Path to a PDF, TXT, MD, or TeX paper.")
    parser.add_argument("--out-dir", required=True, help="Directory for generated artifacts.")
    parser.add_argument("--venue", default="acmmm", help="Venue or review style. Default: acmmm.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_INSTRUCTIONS),
        default="peer-review",
        help="Reviewer profile. Use supervisor for pre-submission audit or adversarial for harsher score calibration.",
    )
    parser.add_argument("--stress-test", action="store_true", help="Run an additional supervisor meta-review pass.")
    parser.add_argument("--resume", action="store_true", help="Reuse existing artifacts in --out-dir when present.")
    parser.add_argument("--max-chars", type=int, default=70000, help="Max paper characters sent to each external model.")
    parser.add_argument("--stress-max-chars", type=int, default=30000, help="Max paper characters sent to stress-test prompts.")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds for each provider.")
    parser.add_argument("--skip-claude", action="store_true", help="Do not call Claude Code.")
    parser.add_argument("--skip-gemini", action="store_true", help="Do not call Gemini.")
    parser.add_argument("--claude-model", default=None, help="Override Claude model.")
    parser.add_argument("--claude-budget", default=None, help="Optional Claude --max-budget-usd value.")
    parser.add_argument(
        "--gemini-models",
        default=",".join(DEFAULT_GEMINI_MODELS),
        help="Comma-separated Gemini fallback model list.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paper_path = pathlib.Path(args.paper).expanduser().resolve()
    out_dir = pathlib.Path(args.out_dir).expanduser().resolve()
    if not paper_path.exists():
        print(f"Paper not found: {paper_path}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "paper": str(paper_path),
        "venue": args.venue,
        "profile": args.profile,
        "stress_test": args.stress_test,
        "resume": args.resume,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "providers": {},
    }

    try:
        paper_text, extraction_method = extract_paper_text(paper_path, out_dir, args.resume)
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 3
    write_text(out_dir / "paper_text.txt", paper_text)
    meta["extraction_method"] = extraction_method
    meta["paper_characters"] = len(paper_text)

    prompt_text = compact_text(paper_text, args.max_chars)
    reviewer_prompt = build_reviewer_prompt(prompt_text, args.venue, args.profile)
    write_text(out_dir / "provider_prompt.md", reviewer_prompt)

    gemini_models = [item.strip() for item in args.gemini_models.split(",") if item.strip()]

    claude_ok, claude_output, claude_model, claude_resumed = run_or_skip(
        out_dir / "claude_review.md",
        args.resume,
        args.skip_claude,
        "Skipped by --skip-claude.",
        lambda: run_claude(reviewer_prompt, args.claude_model, args.timeout, args.claude_budget),
    )
    meta["providers"]["claude"] = {"ok": claude_ok, "model": claude_model, "resumed": claude_resumed}

    gemini_ok, gemini_output, gemini_model, gemini_resumed = run_or_skip(
        out_dir / "gemini_review.md",
        args.resume,
        args.skip_gemini,
        "Skipped by --skip-gemini.",
        lambda: run_gemini(reviewer_prompt, gemini_models, args.timeout),
    )
    meta["providers"]["gemini"] = {
        "ok": gemini_ok,
        "model": gemini_model,
        "models_tried": gemini_models,
        "resumed": gemini_resumed,
    }

    claude_stress_output: str | None = None
    gemini_stress_output: str | None = None
    if args.stress_test:
        stress_prompt = build_stress_prompt(
            compact_text(paper_text, args.stress_max_chars),
            args.venue,
            args.profile,
            claude_output,
            gemini_output,
        )
        write_text(out_dir / "stress_test_prompt.md", stress_prompt)

        claude_stress_ok, claude_stress_output, claude_stress_model, claude_stress_resumed = run_or_skip(
            out_dir / "claude_stress_test.md",
            args.resume,
            args.skip_claude,
            "Skipped by --skip-claude.",
            lambda: run_claude(stress_prompt, args.claude_model, args.timeout, args.claude_budget),
        )
        meta["providers"]["claude_stress"] = {
            "ok": claude_stress_ok,
            "model": claude_stress_model,
            "resumed": claude_stress_resumed,
        }

        gemini_stress_ok, gemini_stress_output, gemini_stress_model, gemini_stress_resumed = run_or_skip(
            out_dir / "gemini_stress_test.md",
            args.resume,
            args.skip_gemini,
            "Skipped by --skip-gemini.",
            lambda: run_gemini(stress_prompt, gemini_models, args.timeout),
        )
        meta["providers"]["gemini_stress"] = {
            "ok": gemini_stress_ok,
            "model": gemini_stress_model,
            "resumed": gemini_stress_resumed,
        }

    combined = textwrap.dedent(
        f"""
        # Multi-Model Paper Review Notes

        Paper: `{paper_path}`
        Venue: `{args.venue}`
        Profile: `{args.profile}`
        Extraction: `{extraction_method}`

        ## Claude Code

        Status: {"ok" if claude_ok else "failed/skipped"}
        Model: `{claude_model or "n/a"}`

        {claude_output}

        ## Gemini

        Status: {"ok" if gemini_ok else "failed/skipped"}
        Model: `{gemini_model or "n/a"}`

        {gemini_output}
        """
    ).strip()
    if claude_stress_output or gemini_stress_output:
        combined += textwrap.dedent(
            f"""

            ## Claude Supervisor Stress Test

            {claude_stress_output or "Not run."}

            ## Gemini Supervisor Stress Test

            {gemini_stress_output or "Not run."}
            """
        ).rstrip()
    write_text(out_dir / "combined_notes.md", combined)

    synthesis_prompt = build_synthesis_prompt(
        args.venue,
        args.profile,
        paper_path,
        paper_text,
        claude_output,
        gemini_output,
        claude_stress_output,
        gemini_stress_output,
    )
    write_text(out_dir / "codex_synthesis_prompt.md", synthesis_prompt)

    meta["status"] = "ready_for_codex_synthesis"
    write_json(out_dir / "paper_meta.json", meta)
    write_json(out_dir / "review_state.json", meta)

    manifest_descriptions = {
        "paper_text.txt": "Extracted paper text used as the evidence base.",
        "provider_prompt.md": "Prompt sent to first-round external reviewers.",
        "claude_review.md": "Raw Claude Code reviewer output or failure note.",
        "gemini_review.md": "Raw Gemini reviewer output or failure note.",
        "stress_test_prompt.md": "Prompt sent for optional supervisor stress-test pass.",
        "claude_stress_test.md": "Raw Claude Code supervisor stress-test output.",
        "gemini_stress_test.md": "Raw Gemini supervisor stress-test output.",
        "combined_notes.md": "Combined provider notes for human inspection.",
        "codex_synthesis_prompt.md": "Prompt for Codex final review synthesis.",
        "paper_meta.json": "Machine-readable extraction and provider metadata.",
        "review_state.json": "Resume-friendly state file for this review run.",
    }
    write_text(out_dir / "MANIFEST.md", artifact_table(out_dir, manifest_descriptions))

    print(f"Wrote review artifacts to: {out_dir}")
    print(f"Profile: {args.profile}")
    print(f"Claude: {'ok' if claude_ok else 'failed/skipped'} ({claude_model or 'n/a'})")
    print(f"Gemini: {'ok' if gemini_ok else 'failed/skipped'} ({gemini_model or 'n/a'})")
    if args.stress_test:
        print("Stress test: enabled")
    print(f"Next: ask Codex to synthesize using {out_dir / 'codex_synthesis_prompt.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
