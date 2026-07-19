#!/usr/bin/env python3

"""
Post-summary hook: post a SHORT meeting summary to Slack (issue #4).

hushnote's run_post_summary_hook invokes this as:

    hooks/slack_publish.py <base>_summary.md

It (1) reads the full markdown summary, (2) runs a SECOND, terser Ollama pass
producing a 3-5 bullet TL;DR plus action items (distinct from the full notes),
(3) renders that to Slack mrkdwn, (4) appends a link to the Confluence page when
one exists (read from the sibling <base>.confluence_page_id marker written by the
Confluence publisher, issue #3), and (5) posts it to a channel via an incoming
webhook or a bot token.

Slack posts are NOT idempotent — an incoming-webhook / chat.postMessage POST
creates a new message every time — so on a confirmed post this hook writes a
sibling <base>.slack_done marker and, on any later invocation, no-ops when that
marker already exists. That makes hook retries safe: at most one Slack message
per meeting regardless of how many times the hook is re-run.

All configuration and secrets come from SLACK_* environment variables (hushnote
sources .hushnoterc before invoking the hook). The bot token and webhook URL are
never printed (redacted from every error). The TL;DR pass reuses the same
OLLAMA_MODEL / OLLAMA_URL as summarize.py (falling back to its defaults, since
hushnote does not export those vars when the user relies on defaults).

The hook exits 0 only on a successful post (or a dry-run, or an already-posted
no-op) and non-zero on any missing-config / Ollama / Slack API error, so hushnote
does not write the .hook_done marker and retries the hook next catchup/process.

Dry-run (--dry-run or SLACK_DRY_RUN=1) resolves everything and prints the short
summary, the resolved Slack target (never a secret), and the exact payload WITHOUT
posting and WITHOUT requiring a token/webhook. It MAY still call the local Ollama
to produce the real TL;DR; tests inject a fake generator so no real Ollama runs.

Stdlib + requests only. The requests import is guarded so the pure-logic helpers
(prompt building, markdown->Slack rendering, link/config/payload assembly) import
and unit-test with no network and no requests installed; only the Ollama call and
the Slack POST need requests.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:  # keep the module importable for pure-logic tests
    requests = None

# Reuse the already-tested pure helpers from the Confluence publisher (both live
# in hooks/, so this resolves when run as a script — the script dir is on
# sys.path — and when hooks/ is put on sys.path in tests). No network on import;
# confluence_publish guards its own requests import the same way.
import confluence_publish as _cp

derive_base_stem = _cp.derive_base_stem
read_metadata = _cp.read_metadata
resolve_meeting_date = _cp.resolve_meeting_date
resolve_meeting_time = _cp.resolve_meeting_time


DEFAULT_TIMEOUT = 30  # seconds, per Slack HTTP request

# Same defaults as summarize.py — hushnote does not export OLLAMA_MODEL/OLLAMA_URL
# when the user relies on the defaults (they are assigned after `set +a`), so the
# hook must fall back to these or it would send an empty model.
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

_TRUTHY = {"1", "true", "yes", "on"}

# The terser second pass: TL;DR + action items only, no other sections.
SLACK_TLDR_PROMPT = """You are an assistant that writes a very short Slack update from a set of meeting notes.

From the meeting notes below, produce ONLY:

- A "TL;DR" of 3-5 bullet points capturing the most important outcomes and decisions.
- An "Action items" list of the concrete next steps that were agreed (with owner and deadline if stated). Omit this list entirely if there are none.

Keep it terse — this is a chat message, not a document. Do not restate the full notes, do not add any other sections, and use only short bullet points. Do not wrap your response in a code block.

Meeting notes:
{summary}"""

# Line classifiers for the Slack mrkdwn renderer.
_SLACK_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_SLACK_TASK_RE = re.compile(r"^[-*+]\s+\[([ xX])\]\s?(.*)$")
_SLACK_ULIST_RE = re.compile(r"^[-*+]\s+(.*)$")
_SLACK_OLIST_RE = re.compile(r"^(\d+)\.\s+(.*)$")

_BULLET = "•"        # •
_BOX_UNCHECKED = "☐"  # ☐
_BOX_CHECKED = "☑"    # ☑


class ConfigError(Exception):
    """Missing / invalid SLACK_* configuration."""


class PublishError(Exception):
    """A Slack post (webhook / chat.postMessage) failed; message is redacted."""


# --------------------------------------------------------------------------- #
# TL;DR generation (pure prompt building + an injectable Ollama seam)
# --------------------------------------------------------------------------- #

def build_tldr_prompt(summary_md):
    """Build the terser second-pass prompt from the full summary markdown. Pure:
    just formats SLACK_TLDR_PROMPT with the summary as the source material."""
    return SLACK_TLDR_PROMPT.format(summary=summary_md)


def _strip_code_fence(text):
    """Strip a wrapping code fence a model sometimes adds around markdown output.
    Local copy of summarize._strip_code_fence so post-processing needs no
    summarize import (that import is deferred behind the Ollama seam)."""
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text.strip()


def _load_query_ollama():
    """Lazily import summarize.query_ollama, ensuring the repo root (the parent of
    this hooks/ dir) is importable. Behind a seam so tests inject a fake and never
    import summarize or touch a real Ollama."""
    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import summarize  # noqa: E402 (deferred on purpose)
    return summarize.query_ollama


def generate_tldr(summary_md, model, ollama_url, ollama_fn=None):
    """Produce the short TL;DR from the full summary via a second Ollama pass.
    ollama_fn is the seam: default lazily loads summarize.query_ollama; tests pass
    a fake callable (prompt, model=, ollama_url=) -> str. The raw response is run
    through _strip_code_fence so a fenced reply is unwrapped."""
    prompt = build_tldr_prompt(summary_md)
    fn = ollama_fn or _load_query_ollama()
    raw = fn(prompt, model=model, ollama_url=ollama_url)
    return _strip_code_fence(raw)


# --------------------------------------------------------------------------- #
# Markdown -> Slack mrkdwn (pure; Slack mrkdwn differs from GitHub markdown)
# --------------------------------------------------------------------------- #

def _slack_inline(text):
    """Convert inline markdown emphasis/code on one line to Slack mrkdwn.

    Slack bold is a single *asterisk* and italic is _underscore_. Protect `code`
    spans (Slack supports backticks, leave literal), convert **b**/__b__ to Slack
    *b* stashed behind placeholders so the italic pass cannot grab those single
    asterisks, then *i* -> _i_ (requiring non-space just inside the delimiters so
    a literal "2 * 3" is not italicized). Markdown _i_ is already Slack italic and
    is left as-is."""
    stash = []

    def _stash(s):
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`[^`]+`", lambda m: _stash(m.group(0)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: _stash("*" + m.group(1) + "*"), text)
    text = re.sub(r"__([^_]+)__", lambda m: _stash("*" + m.group(1) + "*"), text)
    text = re.sub(r"\*(?!\s)([^*]+?)(?<!\s)\*", r"_\1_", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def markdown_to_slack(md):
    """Render the terser TL;DR markdown as Slack mrkdwn.

    Slack has no # headings and does not render markdown '-' lists, so: ATX
    headings become a bold line, unordered items become '• ', checklist items
    become '• ☐ '/'• ☑ ', ordered items keep their 'N. ' number, and inline
    emphasis/code is converted per _slack_inline. Blank lines are preserved as
    paragraph breaks; runs of 3+ blank lines collapse to one. Returns a compact
    mrkdwn string. Links (<url|label>) are added later in build_message_text."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue

        m = _SLACK_HEADING_RE.match(stripped)
        if m:
            out.append("*" + _slack_inline(m.group(1).strip()) + "*")
            continue

        tm = _SLACK_TASK_RE.match(stripped)
        if tm:
            box = _BOX_CHECKED if tm.group(1).lower() == "x" else _BOX_UNCHECKED
            out.append(f"{_BULLET} {box} " + _slack_inline(tm.group(2).strip()))
            continue

        um = _SLACK_ULIST_RE.match(stripped)
        if um:
            out.append(f"{_BULLET} " + _slack_inline(um.group(1).strip()))
            continue

        om = _SLACK_OLIST_RE.match(stripped)
        if om:
            out.append(f"{om.group(1)}. " + _slack_inline(om.group(2).strip()))
            continue

        out.append(_slack_inline(stripped))

    text = "\n".join(out).strip("\n")
    return re.sub(r"\n{3,}", "\n\n", text)


# --------------------------------------------------------------------------- #
# Confluence link + message assembly (pure)
# --------------------------------------------------------------------------- #

def read_page_id(base_dir, base):
    """Read the sibling <base>.confluence_page_id marker (written by issue #3) and
    return the stripped page id, or None when the marker is absent / unreadable /
    empty. Tolerant: never raises."""
    path = Path(base_dir) / f"{base}.confluence_page_id"
    try:
        pid = path.read_text().strip()
    except OSError:
        return None
    return pid or None


def build_confluence_link(base_url, page_id):
    """Build the page URL from CONFLUENCE_BASE_URL + a page id, or None when
    either is missing. The /pages/viewpage.action?pageId=<id> form resolves on
    both Confluence Cloud and Server/Data Center."""
    if not base_url or not page_id:
        return None
    return f"{base_url.rstrip('/')}/pages/viewpage.action?pageId={page_id}"


def _message_header(title, date, time):
    """A one-line header from the human meeting title and date/time. Degrades to
    'Meeting notes' (optionally with the date/time) when there is no title."""
    title = (title or "").strip()
    when = " ".join(x for x in (date, time) if x)
    if title and when:
        return f"{title} — {when}"
    if title:
        return title
    if when:
        return f"Meeting notes — {when}"
    return "Meeting notes"


def build_message_text(short_summary, title=None, date=None, time=None, confluence_link=None):
    """Assemble the final Slack message (mrkdwn): a bold header (meeting title +
    date/time), the short summary, then a 'Full meeting notes on Confluence' link
    line when a link is available (omitted gracefully otherwise). Links use
    Slack's <url|label> syntax."""
    parts = ["*" + _message_header(title, date, time) + "*", short_summary.strip()]
    if confluence_link:
        parts.append(f"<{confluence_link}|Full meeting notes on Confluence>")
    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Config / target resolution (no network)
# --------------------------------------------------------------------------- #

def resolve_mode(env):
    """'webhook', 'bot', or None. SLACK_AUTH_MODE forces 'webhook'/'bot' when set
    to either; otherwise webhook if SLACK_WEBHOOK_URL is set, else bot if
    SLACK_BOT_TOKEN is set, else None (both set -> webhook wins)."""
    mode = (env.get("SLACK_AUTH_MODE") or "").strip().lower()
    if mode in ("webhook", "bot"):
        return mode
    if (env.get("SLACK_WEBHOOK_URL") or "").strip():
        return "webhook"
    if (env.get("SLACK_BOT_TOKEN") or "").strip():
        return "bot"
    return None


def resolve_config(env):
    """Build a config dict from the SLACK_* (and OLLAMA_*/CONFLUENCE_BASE_URL) env
    vars. The bot token is carried verbatim (never trimmed) and never logged; the
    webhook URL is a request URL so it is stripped, but it is a credential too and
    is redacted from all output. OLLAMA_* fall back to summarize's defaults."""
    return {
        "webhook_url": (env.get("SLACK_WEBHOOK_URL") or "").strip(),
        "bot_token": env.get("SLACK_BOT_TOKEN") or "",
        "channel": (env.get("SLACK_CHANNEL") or "").strip(),
        "mode": resolve_mode(env),
        "ollama_model": (env.get("OLLAMA_MODEL") or "").strip() or DEFAULT_OLLAMA_MODEL,
        "ollama_url": (env.get("OLLAMA_URL") or "").strip() or DEFAULT_OLLAMA_URL,
        "confluence_base_url": (env.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/"),
        "dry_run": (env.get("SLACK_DRY_RUN") or "").strip().lower() in _TRUTHY,
    }


def validate_required(cfg):
    """Raise ConfigError naming every missing required var for the resolved mode.
    Webhook mode needs SLACK_WEBHOOK_URL; bot mode needs SLACK_BOT_TOKEN and
    SLACK_CHANNEL; no mode at all means no target is configured."""
    mode = cfg["mode"]
    if mode is None:
        raise ConfigError(
            "No Slack target configured. Set SLACK_WEBHOOK_URL (incoming webhook) "
            "or SLACK_BOT_TOKEN + SLACK_CHANNEL (bot token) in .hushnoterc "
            "(see .hushnoterc.example)."
        )
    if mode == "webhook":
        missing = [] if cfg["webhook_url"] else ["SLACK_WEBHOOK_URL"]
    else:  # bot
        missing = []
        if not cfg["bot_token"]:
            missing.append("SLACK_BOT_TOKEN")
        if not cfg["channel"]:
            missing.append("SLACK_CHANNEL")
    if missing:
        raise ConfigError(
            f"Missing required Slack configuration for {mode} mode: "
            + ", ".join(missing)
            + ". Set these in .hushnoterc (see .hushnoterc.example)."
        )


def build_payload(cfg, text):
    """Slack POST body. Webhook: {'text': ...}; bot: {'channel': ..., 'text': ...}.
    Carries no secret (the bot token travels in the Authorization header, not the
    body), so it is safe to print in dry-run. Mode None falls back to the webhook
    shape purely so a dry-run with no target can still show a preview."""
    if cfg["mode"] == "bot":
        return {"channel": cfg["channel"], "text": text}
    return {"text": text}


def describe_target(cfg):
    """Human description of the resolved target with NO secret in it."""
    mode = cfg["mode"]
    if mode == "webhook":
        return "incoming webhook (URL hidden)"
    if mode == "bot":
        return f"channel {cfg['channel'] or '(unset)'} via bot token"
    return "(no SLACK target configured)"


def should_skip(marker_path):
    """True when the <base>.slack_done marker already exists -> already posted, so
    a re-run must NOT post again (Slack is not idempotent)."""
    return Path(marker_path).exists()


# --------------------------------------------------------------------------- #
# Network layer (needs requests) -- exercised only against a live Slack
# --------------------------------------------------------------------------- #

def _redact(text, cfg):
    """Never leak a credential: scrub BOTH the bot token and the webhook URL from
    the text and truncate. Both are secrets."""
    text = str(text)
    for secret in (cfg.get("bot_token"), cfg.get("webhook_url")):
        if secret and secret in text:
            text = text.replace(secret, "***")
    return text[:500]


def post_to_slack(cfg, payload):
    """Post the message. Webhook: POST the body to the webhook URL; success is
    HTTP 200 with an 'ok' body. Bot: POST to chat.postMessage with a Bearer token;
    Slack returns HTTP 200 even on failure, so success requires resp.json()['ok']
    is true (otherwise raise, so a failed post is never treated as success and no
    .slack_done marker is written)."""
    if requests is None:
        raise PublishError(
            "The 'requests' library is required to post to Slack. "
            "Install with: pip install requests"
        )

    if cfg["mode"] == "webhook":
        resp = requests.post(cfg["webhook_url"], json=payload, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200 or resp.text.strip().lower() != "ok":
            raise PublishError(
                f"Slack webhook post failed: HTTP {resp.status_code}: {_redact(resp.text, cfg)}"
            )
        return

    headers = {
        "Authorization": "Bearer " + cfg["bot_token"],
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post(
        SLACK_POST_MESSAGE_URL, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT
    )
    if resp.status_code != 200:
        raise PublishError(
            f"Slack chat.postMessage failed: HTTP {resp.status_code}: {_redact(resp.text, cfg)}"
        )
    try:
        data = resp.json()
    except ValueError:
        raise PublishError(
            f"Slack chat.postMessage returned non-JSON: {_redact(resp.text, cfg)}"
        )
    if not data.get("ok"):
        raise PublishError(
            f"Slack chat.postMessage error: {_redact(data.get('error') or resp.text, cfg)}"
        )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None, ollama_fn=None):
    parser = argparse.ArgumentParser(
        description="Post a short HushNote meeting summary to Slack (post-summary hook)."
    )
    parser.add_argument("summary_file", help="Path to the <base>_summary.md file")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve everything and print the short summary, target and payload "
             "without posting (no token/webhook required). May still call the local "
             "Ollama for the TL;DR. Also enabled by SLACK_DRY_RUN=1.",
    )
    args = parser.parse_args(argv)

    summary_path = Path(args.summary_file)
    if not summary_path.exists():
        print(f"Error: summary file not found: {summary_path}", file=sys.stderr)
        return 1

    try:
        md = summary_path.read_text()
    except OSError as e:
        print(f"Error: cannot read summary file: {e}", file=sys.stderr)
        return 1

    base = derive_base_stem(summary_path)
    base_dir = summary_path.parent
    metadata = read_metadata(base_dir, base)
    title = str(metadata.get("title", "")).strip()
    date = resolve_meeting_date(metadata, base)
    time = resolve_meeting_time(metadata, base)

    cfg = resolve_config(os.environ)
    dry_run = args.dry_run or cfg["dry_run"]

    marker_path = str(base_dir / f"{base}.slack_done")

    # Already posted? Slack is not idempotent, so no-op success (never re-post).
    # Checked before the Ollama call so a re-run wastes no work. Dry-run still
    # previews (it writes nothing).
    if not dry_run and should_skip(marker_path):
        print(
            f"Slack: already posted (marker exists: {marker_path}); skipping.",
            file=sys.stderr,
        )
        return 0

    # Fail fast on missing config BEFORE the (potentially slow) Ollama pass, so a
    # misconfigured real run doesn't burn an Ollama call on every retry. Dry-run
    # deliberately skips validation (it needs no token/webhook to preview).
    if not dry_run:
        try:
            validate_required(cfg)
        except ConfigError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Confluence link when available (marker from #3 + CONFLUENCE_BASE_URL).
    page_id = read_page_id(base_dir, base)
    confluence_link = build_confluence_link(cfg["confluence_base_url"], page_id)

    # Second, terser Ollama pass -> the short summary.
    try:
        short_summary = generate_tldr(
            md, cfg["ollama_model"], cfg["ollama_url"], ollama_fn=ollama_fn
        )
    except SystemExit:
        # summarize.query_ollama does sys.exit(1) on an Ollama error; surface it as
        # a non-zero hook exit (so hushnote retries) rather than exiting the process.
        print("Error: Ollama TL;DR generation failed (see message above).", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error generating TL;DR: {_redact(e, cfg)}", file=sys.stderr)
        return 1

    slack_summary = markdown_to_slack(short_summary)
    message = build_message_text(slack_summary, title, date, time, confluence_link)

    if dry_run:
        print("=== Slack publish (dry-run) ===")
        print(f"TARGET:          {describe_target(cfg)}")
        print(f"CONFLUENCE LINK: {confluence_link or '(none)'}")
        print("=== short summary (Slack mrkdwn) ===")
        print(message)
        print("=== payload ===")
        print(json.dumps(build_payload(cfg, message), indent=2, ensure_ascii=False))
        return 0

    payload = build_payload(cfg, message)
    try:
        post_to_slack(cfg, payload)
    except PublishError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # network / requests errors -- redact any secret
        print(f"Error posting to Slack: {_redact(e, cfg)}", file=sys.stderr)
        return 1

    # Confirmed post -> write the dedup marker so retries never re-post. Unlike the
    # best-effort markers elsewhere, this one is a hard dedup invariant for a
    # NON-idempotent target: if it can't be written we can't return non-zero (that
    # would force a retry and double-post the message), so surface it loudly instead
    # of swallowing it, so the operator knows a retry could duplicate the post.
    try:
        Path(marker_path).write_text("posted\n")
    except OSError as e:
        print(
            f"Warning: Slack message posted but could not write dedup marker "
            f"{marker_path}: {e}. A hook retry may post a duplicate.",
            file=sys.stderr,
        )

    print(f"Slack: posted meeting summary via {cfg['mode']} target.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
