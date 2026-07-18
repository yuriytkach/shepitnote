#!/usr/bin/env python3

"""
Post-summary hook: publish a HushNote meeting summary to Confluence (issue #3).

hushnote's run_post_summary_hook invokes this as:

    hooks/confluence_publish.py <base>_summary.md

It (1) reads the markdown summary, (2) reads the sibling <base>_metadata.json for
the human title and date, (3) resolves a stable page title, (4) converts the
markdown to Confluence storage-format XHTML, and (5) creates-or-updates a page in
the configured space via the REST content API. Re-running on the same meeting
updates the same page (idempotent), never duplicating.

All configuration and secrets come from CONFLUENCE_* environment variables
(hushnote sources .hushnoterc before invoking the hook). Nothing is hardcoded and
the API token is never printed. The hook exits 0 only on a successful publish (or
a dry-run) and non-zero on any missing-config / API / network error, so hushnote
does not write the .hook_done marker and retries the hook next catchup/process.

Cloud (Confluence Cloud, REST v1) is the primary target: HTTP Basic with
email:token. Server / Data Center is supported via the same code path using a
Bearer Personal Access Token. The auth scheme is picked from CONFLUENCE_AUTH_MODE
(when set) else derived from whether CONFLUENCE_EMAIL is present.

Dry-run (--dry-run or CONFLUENCE_DRY_RUN=1) resolves the title/space/parent and
prints the storage-format XHTML to stdout WITHOUT calling the API or needing
credentials -- the way to preview output before a real publish, and how the
converter is exercised in tests.

Confirm-gating (issue #5) is out of scope here: the hook simply publishes when
invoked. It is opt-in via POST_SUMMARY_HOOK.

Stdlib + requests only. The requests import is guarded so the pure-logic helpers
(markdown conversion, title/metadata/config resolution) import and unit-test with
no network and no requests installed; only the HTTP layer needs requests.
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


DEFAULT_TIMEOUT = 30  # seconds, per HTTP request

# Required CONFLUENCE_* config for a real publish: (cfg key, env var name).
REQUIRED = (
    ("base_url", "CONFLUENCE_BASE_URL"),
    ("space_key", "CONFLUENCE_SPACE_KEY"),
    ("api_token", "CONFLUENCE_API_TOKEN"),
)

_TRUTHY = {"1", "true", "yes", "on"}

# YYYYMMDD_HHMMSS embedded in a base stem like meeting_20260718_233340.
_BASE_TS_RE = re.compile(r"(\d{8})_(\d{6})")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TASK_RE = re.compile(r"^[-*+]\s+\[([ xX])\]\s?(.*)$")
_ULIST_RE = re.compile(r"^[-*+]\s+(.*)$")
_OLIST_RE = re.compile(r"^(\d+)\.\s+(.*)$")


class ConfigError(Exception):
    """Missing / invalid CONFLUENCE_* configuration."""


class PublishError(Exception):
    """A publish (search / create / update) failed; message is token-redacted."""


# --------------------------------------------------------------------------- #
# Pure helpers: base stem, metadata, title/date resolution (no network)
# --------------------------------------------------------------------------- #

def derive_base_stem(summary_path):
    """Strip a trailing _summary.md/.txt/.json (or bare _summary) from the summary
    filename, giving the canonical meeting base stem, e.g. meeting_20260718_233340."""
    name = Path(summary_path).name
    for suffix in ("_summary.md", "_summary.txt", "_summary.json", "_summary"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def read_metadata(base_dir, base):
    """Read {base}_metadata.json from base_dir. Tolerant: a missing file or invalid
    JSON (or non-object JSON) yields an empty dict; never raises."""
    path = Path(base_dir) / f"{base}_metadata.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_meeting_date(metadata, base):
    """YYYY-MM-DD from metadata['date'] (YYYYMMDD), else the date group of the base
    stem, else None."""
    raw = str(metadata.get("date", "")).strip()
    if not re.fullmatch(r"\d{8}", raw):
        m = _BASE_TS_RE.search(base)
        raw = m.group(1) if m else ""
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


def resolve_meeting_time(metadata, base):
    """HH:MM from metadata['timestamp'] (YYYYMMDD_HHMMSS), else the time group of the
    base stem, else None."""
    ts = str(metadata.get("timestamp", "")).strip()
    m = re.search(r"\d{8}_(\d{6})", ts)
    hhmmss = m.group(1) if m else ""
    if not re.fullmatch(r"\d{6}", hhmmss):
        m2 = _BASE_TS_RE.search(base)
        hhmmss = m2.group(2) if m2 else ""
    if re.fullmatch(r"\d{6}", hhmmss):
        return f"{hhmmss[0:2]}:{hhmmss[2:4]}"
    return None


def resolve_page_title(metadata, base):
    """Stable page title for a meeting. With a human title ->
    '<title> - YYYY-MM-DD HH:MM'; without -> 'Meeting HH:MM - YYYY-MM-DD'. The time
    disambiguates two meetings with the same title on the same day -- Confluence
    requires unique titles per space, so without it the second meeting would
    overwrite the first's page. Degrades gracefully when date/time are unresolvable.
    Deterministic for a given meeting (the timestamp is fixed), so re-runs map to
    the same page, which is what makes update-if-exists idempotency work. Truncated
    to Confluence's 255-character title limit."""
    title = str(metadata.get("title", "")).strip()
    date = resolve_meeting_date(metadata, base)
    time = resolve_meeting_time(metadata, base)
    if title:
        if date and time:
            result = f"{title} - {date} {time}"
        elif date:
            result = f"{title} - {date}"
        else:
            result = title
    elif time and date:
        result = f"Meeting {time} - {date}"
    elif date:
        result = f"Meeting - {date}"
    elif time:
        result = f"Meeting {time}"
    else:
        result = base
    return result[:255]


# --------------------------------------------------------------------------- #
# Markdown -> Confluence storage-format XHTML (stdlib only, no markdown lib)
# --------------------------------------------------------------------------- #

def escape(text, quote=False):
    """XML-escape a text run. & first, then < and >, plus \" in attribute mode.
    *, _ and backtick are not XML-special so they survive, letting escaping and
    inline-markdown conversion run without colliding."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        text = text.replace('"', "&quot;")
    return text


def _apply_inline(text):
    """Apply inline markdown to an already-XML-escaped text run: protect `code`
    spans, then **/__ bold, then */_ italic. Code spans are shielded from
    bold/italic conversion via placeholders."""
    stash = []

    def _protect(m):
        stash.append(m.group(1))
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _protect, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    # Require non-space just inside the delimiters so a literal "2 * 3 * 4" is not
    # italicized (emphasis markers hug their text; " * " is multiplication/glob).
    text = re.sub(r"\*(?!\s)([^*]+?)(?<!\s)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w`])_([^_]+)_(?![\w`])", r"<em>\1</em>", text)

    def _restore(m):
        return f"<code>{stash[int(m.group(1))]}</code>"

    return re.sub(r"\x00(\d+)\x00", _restore, text)


def _inline(text):
    """Escape then apply inline markdown -- the common path for headings,
    paragraphs, list items and task bodies."""
    return _apply_inline(escape(text))


def _render_code_block(code, lang):
    """Fenced code -> Confluence code macro. Content is left literal inside CDATA
    (not XML-escaped); any literal ]]> is split so the CDATA stays valid."""
    safe = code.replace("]]>", "]]]]><![CDATA[>")
    parts = ['<ac:structured-macro ac:name="code">']
    if lang:
        parts.append(f'<ac:parameter ac:name="language">{escape(lang)}</ac:parameter>')
    parts.append(f"<ac:plain-text-body><![CDATA[{safe}]]></ac:plain-text-body>")
    parts.append("</ac:structured-macro>")
    return "".join(parts)


def _render_task_list(items):
    """items: list of (task_id, status, body_xhtml) -> ac:task-list markup."""
    parts = ["<ac:task-list>"]
    for tid, status, body in items:
        parts.append(
            "<ac:task>"
            f"<ac:task-id>{tid}</ac:task-id>"
            f"<ac:task-status>{status}</ac:task-status>"
            f"<ac:task-body><span>{body}</span></ac:task-body>"
            "</ac:task>"
        )
    parts.append("</ac:task-list>")
    return "".join(parts)


def markdown_to_storage(md):
    """Convert summary markdown to Confluence storage-format XHTML.

    Handles what summarize.py emits: #/##/### headings, **bold** / *italic*,
    unordered and ordered lists, an Action Items checklist (- [ ] / - [x]) as a
    Confluence task list, paragraphs, inline `code`, and fenced code blocks.
    Unknown lines degrade to paragraphs rather than failing."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = len(lines)
    blocks = []
    task_counter = 0
    i = 0

    while i < n:
        stripped = lines[i].strip()

        # blank line -> block separator
        if not stripped:
            i += 1
            continue

        # fenced code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:  # skip the closing fence
                i += 1
            blocks.append(_render_code_block("\n".join(code_lines), lang))
            continue

        # ATX heading
        m = _HEADING_RE.match(stripped)
        if m:
            level = min(len(m.group(1)), 6)
            blocks.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        # task list (checklist): consecutive - [ ] / - [x]
        if _TASK_RE.match(stripped):
            items = []
            while i < n:
                tm = _TASK_RE.match(lines[i].strip())
                if not tm:
                    break
                status = "complete" if tm.group(1).lower() == "x" else "incomplete"
                task_counter += 1
                items.append((task_counter, status, _inline(tm.group(2).strip())))
                i += 1
            blocks.append(_render_task_list(items))
            continue

        # unordered list (excluding task items, handled above)
        if _ULIST_RE.match(stripped):
            items = []
            while i < n:
                s = lines[i].strip()
                if not _ULIST_RE.match(s) or _TASK_RE.match(s):
                    break
                items.append(_inline(_ULIST_RE.match(s).group(1).strip()))
                i += 1
            blocks.append("<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue

        # ordered list
        if _OLIST_RE.match(stripped):
            items = []
            while i < n:
                om = _OLIST_RE.match(lines[i].strip())
                if not om:
                    break
                items.append(_inline(om.group(2).strip()))
                i += 1
            blocks.append("<ol>" + "".join(f"<li>{it}</li>" for it in items) + "</ol>")
            continue

        # paragraph: gather consecutive lines until a blank line or a new block
        para = []
        while i < n and lines[i].strip() and not _starts_block(lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        blocks.append(f"<p>{_inline(' '.join(para))}</p>")

    return "\n".join(blocks)


def _starts_block(stripped):
    """True if a (stripped) line begins a non-paragraph block, so paragraph
    accumulation stops at it."""
    return bool(
        stripped.startswith("```")
        or _HEADING_RE.match(stripped)
        or _ULIST_RE.match(stripped)
        or _OLIST_RE.match(stripped)
    )


# --------------------------------------------------------------------------- #
# Config / auth resolution (no network)
# --------------------------------------------------------------------------- #

def resolve_auth_mode(env):
    """'basic' or 'bearer'. CONFLUENCE_AUTH_MODE forces it when set to either;
    otherwise: an email present -> basic (Cloud), else -> bearer (Server/DC PAT)."""
    mode = (env.get("CONFLUENCE_AUTH_MODE") or "").strip().lower()
    if mode in ("basic", "bearer"):
        return mode
    return "basic" if (env.get("CONFLUENCE_EMAIL") or "").strip() else "bearer"


def resolve_config(env):
    """Build a config dict from the CONFLUENCE_* env vars. The token is carried
    verbatim (never trimmed/altered) and never logged. auth_mode is the resolved
    'basic'/'bearer'."""
    return {
        "base_url": (env.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/"),
        "space_key": (env.get("CONFLUENCE_SPACE_KEY") or "").strip(),
        "api_token": env.get("CONFLUENCE_API_TOKEN") or "",
        "email": (env.get("CONFLUENCE_EMAIL") or "").strip(),
        "parent_page_id": (env.get("CONFLUENCE_PARENT_PAGE_ID") or "").strip(),
        "auth_mode": resolve_auth_mode(env),
        "dry_run": (env.get("CONFLUENCE_DRY_RUN") or "").strip().lower() in _TRUTHY,
    }


def validate_required(cfg):
    """Raise ConfigError naming every missing required var (real-publish path only)."""
    missing = [envname for key, envname in REQUIRED if not cfg.get(key)]
    if missing:
        raise ConfigError(
            "Missing required Confluence configuration: "
            + ", ".join(missing)
            + ". Set these in .hushnoterc (see .hushnoterc.example)."
        )
    if cfg["auth_mode"] == "basic" and not cfg["email"]:
        raise ConfigError(
            "Basic auth selected but CONFLUENCE_EMAIL is not set. Set CONFLUENCE_EMAIL "
            "(Cloud) or CONFLUENCE_AUTH_MODE=bearer (Server/DC PAT)."
        )


# --------------------------------------------------------------------------- #
# HTTP layer (needs requests) -- exercised only against a live Confluence
# --------------------------------------------------------------------------- #

def _redact(text, cfg):
    """Never leak the token: replace any occurrence with *** and truncate."""
    token = cfg.get("api_token") or ""
    text = str(text)
    if token and token in text:
        text = text.replace(token, "***")
    return text[:500]


def _http(cfg, method, url, params=None, json_body=None):
    if requests is None:
        raise PublishError(
            "The 'requests' library is required to publish to Confluence. "
            "Install with: pip install requests"
        )
    headers = {"Accept": "application/json"}
    auth = None
    if cfg["auth_mode"] == "basic":
        auth = (cfg["email"], cfg["api_token"])
    else:
        headers["Authorization"] = "Bearer " + cfg["api_token"]
    return requests.request(
        method, url, params=params, json=json_body,
        headers=headers, auth=auth, timeout=DEFAULT_TIMEOUT,
    )


def find_page(cfg, title):
    """Look up an existing page by exact title in the space. Returns
    (page_id, version_number) or (None, None)."""
    url = f"{cfg['base_url']}/rest/api/content"
    params = {"type": "page", "spaceKey": cfg["space_key"], "title": title, "expand": "version"}
    resp = _http(cfg, "GET", url, params=params)
    if resp.status_code != 200:
        raise PublishError(f"Confluence search failed: HTTP {resp.status_code}: {_redact(resp.text, cfg)}")
    results = resp.json().get("results", [])
    if results:
        page = results[0]
        return page.get("id"), page.get("version", {}).get("number", 1)
    return None, None


def get_page_by_id(cfg, page_id):
    """Fetch a page by id (marker-file fallback for Cloud index lag). Returns
    (page_id, version_number) or (None, None)."""
    url = f"{cfg['base_url']}/rest/api/content/{page_id}"
    resp = _http(cfg, "GET", url, params={"expand": "version"})
    if resp.status_code == 200:
        data = resp.json()
        return data.get("id"), data.get("version", {}).get("number", 1)
    return None, None


def _body_payload(cfg, title, xhtml):
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": cfg["space_key"]},
        "body": {"storage": {"value": xhtml, "representation": "storage"}},
    }
    if cfg["parent_page_id"]:
        payload["ancestors"] = [{"id": cfg["parent_page_id"]}]
    return payload


def create_page(cfg, title, xhtml):
    url = f"{cfg['base_url']}/rest/api/content"
    resp = _http(cfg, "POST", url, json_body=_body_payload(cfg, title, xhtml))
    if resp.status_code not in (200, 201):
        raise PublishError(f"Confluence create failed: HTTP {resp.status_code}: {_redact(resp.text, cfg)}")
    return resp.json().get("id")


def update_page(cfg, page_id, title, xhtml, current_version):
    url = f"{cfg['base_url']}/rest/api/content/{page_id}"
    payload = _body_payload(cfg, title, xhtml)
    payload["id"] = page_id
    payload["version"] = {"number": current_version + 1}
    resp = _http(cfg, "PUT", url, json_body=payload)
    if resp.status_code != 200:
        raise PublishError(f"Confluence update failed: HTTP {resp.status_code}: {_redact(resp.text, cfg)}")
    return page_id


def publish(cfg, title, xhtml, marker_path=None):
    """Create-or-update the page. Title search first; a sibling marker file is a
    supplementary fallback lookup when the search is empty (Cloud index lag).
    Returns ('created'|'updated', page_id). Writes the page id to marker_path on
    success (best-effort)."""
    page_id, version = find_page(cfg, title)

    if page_id is None and marker_path and Path(marker_path).exists():
        try:
            stored = Path(marker_path).read_text().strip()
        except OSError:
            stored = ""
        if stored:
            page_id, version = get_page_by_id(cfg, stored)

    if page_id:
        update_page(cfg, page_id, title, xhtml, version or 1)
        action, result_id = "updated", page_id
    else:
        result_id = create_page(cfg, title, xhtml)
        action = "created"

    if marker_path and result_id:
        try:
            Path(marker_path).write_text(str(result_id) + "\n")
        except OSError:
            pass

    return action, result_id


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Publish a HushNote meeting summary to Confluence (post-summary hook)."
    )
    parser.add_argument("summary_file", help="Path to the <base>_summary.md file")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve the title and print the storage-format XHTML without calling "
             "the API (no credentials required). Also enabled by CONFLUENCE_DRY_RUN=1.",
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
    title = resolve_page_title(metadata, base)
    xhtml = markdown_to_storage(md)

    cfg = resolve_config(os.environ)
    dry_run = args.dry_run or cfg["dry_run"]

    if dry_run:
        print("=== Confluence publish (dry-run) ===")
        print(f"TITLE:    {title}")
        print(f"SPACE:    {cfg['space_key'] or '(not set)'}")
        print(f"PARENT:   {cfg['parent_page_id'] or '(not set)'}")
        print(f"BASE_URL: {cfg['base_url'] or '(not set)'}")
        print(f"AUTH:     {cfg['auth_mode']}")
        print("=== storage-format XHTML ===")
        print(xhtml)
        return 0

    try:
        validate_required(cfg)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    marker_path = str(base_dir / f"{base}.confluence_page_id")
    try:
        action, page_id = publish(cfg, title, xhtml, marker_path)
    except PublishError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # network / requests errors -- redact any token
        print(f"Error publishing to Confluence: {_redact(e, cfg)}", file=sys.stderr)
        return 1

    print(f"Confluence page {action}: {title!r} (id {page_id})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
