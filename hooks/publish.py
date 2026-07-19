#!/usr/bin/env python3

"""
Post-summary hook dispatcher: run every configured publisher (issue #4).

There is exactly one POST_SUMMARY_HOOK slot, but a meeting summary can go to more
than one destination — the full notes to Confluence (issue #3) and a short TL;DR
to Slack (issue #4). Point POST_SUMMARY_HOOK at THIS script to run both; it
invokes each bundled publisher as a subprocess based on which env vars are set:

    POST_SUMMARY_HOOK=".../hooks/publish.py"

It receives $1 = <base>_summary.md and exits 0/non-zero exactly like any hook, so
shepitnote's run_post_summary_hook contract is untouched. The standalone publishers
(hooks/confluence_publish.py, hooks/slack_publish.py) remain directly invokable;
users who want only one destination can still point POST_SUMMARY_HOOK straight at
that one.

Ordering is deliberate: Confluence runs FIRST so that its sibling
<base>.confluence_page_id marker exists before the Slack publisher reads it —
letting the Slack message include the Confluence link within the same invocation.

Because a Slack post is NOT idempotent (Slack writes a <base>.slack_done marker on
its first successful post and never posts again), Slack is GATED on Confluence when
both are enabled: it runs only once the Confluence page id is available — either
Confluence exited 0 this run, or its <base>.confluence_page_id marker already
exists from an earlier run. If Confluence just failed and no page exists yet, Slack
is DEFERRED (held back) this run and the aggregate exit is non-zero, so shepitnote
retries the whole hook; the retry posts the single Slack message WITH the link once
Confluence recovers. Without this gate, a transient Confluence failure would make
Slack post a linkless message and latch .slack_done, permanently losing the link.
(If Confluence is PERMANENTLY broken the hook never completes anyway — shepitnote
keeps retrying it — so deferring Slack until Confluence recovers is the intended
trade-off.)

Each publisher is standalone and independently idempotent: Confluence updates the
same page by stable title / its own marker, and Slack writes a <base>.slack_done
marker and never re-posts. So a whole-hook retry after a partial failure is safe —
a publisher that already succeeded no-ops, only the failed one is retried, and a
deferred Slack post runs on a later retry. Aggregate exit: 0 iff every ENABLED
publisher exited 0 (a marker-driven no-op counts as 0); non-zero if any enabled
publisher failed OR Slack was deferred (so shepitnote does not write .hook_done and
retries). With no publisher configured it warns and returns 0, avoiding an infinite
retry loop on a bare misconfiguration.

Subprocesses inherit os.environ (so the `set -a`-exported .shepitnoterc vars pass
through, including SLACK_DRY_RUN / CONFLUENCE_DRY_RUN) and isolate a crash or
sys.exit in one publisher from the other. Stdlib only.
"""

import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent

# Reuse the publisher's own base-stem derivation so the .confluence_page_id marker
# path matches exactly. confluence_publish guards its requests import, so this adds
# no network on import. Ensure hooks/ is importable whether run as a script (its dir
# is already sys.path[0]) or imported in tests.
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
from confluence_publish import derive_base_stem  # noqa: E402

# Ordered: confluence FIRST so its page-id marker exists before slack reads it.
PUBLISHER_SCRIPTS = {
    "confluence": "confluence_publish.py",
    "slack": "slack_publish.py",
}

# Sentinel status for a Slack post held back this run because the Confluence page id
# isn't available yet (see the module docstring). Aggregated as a failure so the
# hook retries, but reported distinctly from a real error.
DEFERRED = "deferred"


def enabled_publishers(env):
    """Ordered list of publisher names enabled by cheap env presence checks:
    'confluence' when CONFLUENCE_BASE_URL is set, then 'slack' when
    SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN is set. The order (confluence, slack) is
    what makes the Confluence link available to the Slack message."""
    names = []
    if (env.get("CONFLUENCE_BASE_URL") or "").strip():
        names.append("confluence")
    if (env.get("SLACK_WEBHOOK_URL") or "").strip() or (env.get("SLACK_BOT_TOKEN") or "").strip():
        names.append("slack")
    return names


def _subprocess_runner(name, summary_file):
    """Invoke a bundled publisher as a subprocess, inheriting os.environ and
    isolating a crash/sys.exit in one publisher from the others. Returns the child
    exit code (a missing script surfaces as non-zero, not an exception)."""
    script = HOOKS_DIR / PUBLISHER_SCRIPTS[name]
    return subprocess.call([sys.executable, str(script), summary_file])


def confluence_marker_present(summary_file):
    """True when the sibling <base>.confluence_page_id marker (written by the
    Confluence publisher on a successful publish) already exists next to the summary
    file. Derives the base stem exactly as the publishers do."""
    path = Path(summary_file)
    base = derive_base_stem(path)
    return (path.parent / f"{base}.confluence_page_id").exists()


def run_all(summary_file, publishers, runner, marker_present=None):
    """Run each publisher in order via runner(name, summary_file) and aggregate.
    Returns (overall_exit, results) where results is a list of (name, status) and
    status is an int exit code or DEFERRED.

    Gating: when BOTH confluence and slack are enabled, slack is held back
    (DEFERRED) unless the Confluence page id is available — confluence exited 0 this
    run, OR its <base>.confluence_page_id marker already exists (checked via
    marker_present, injectable for tests; defaults to the real filesystem check).
    This stops a transient Confluence failure from making slack post a linkless
    message and latch its .slack_done marker so the link can never be back-filled;
    the deferred post runs on the next retry once Confluence has recovered.

    overall_exit is 0 iff every publisher returned 0 (a marker-driven no-op returns
    0 and counts as success); non-zero if any returned non-zero OR slack was
    deferred."""
    if marker_present is None:
        marker_present = confluence_marker_present
    both = "confluence" in publishers and "slack" in publishers
    results = []
    overall = 0
    codes = {}
    for name in publishers:
        if name == "slack" and both:
            # Ready when confluence succeeded this run (short-circuits the stat) or a
            # page already exists from before; otherwise defer so the retry links.
            ready = codes.get("confluence") == 0 or marker_present(summary_file)
            if not ready:
                results.append((name, DEFERRED))
                overall = 1
                continue
        code = runner(name, summary_file)
        codes[name] = code
        results.append((name, code))
        if code != 0:
            overall = 1
    return overall, results


def main(argv=None, runner=None, env=None, marker_present=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: publish.py <summary_file>", file=sys.stderr)
        return 2
    summary_file = argv[0]

    env = os.environ if env is None else env
    runner = _subprocess_runner if runner is None else runner

    publishers = enabled_publishers(env)
    if not publishers:
        print(
            "Warning: no publisher configured — set CONFLUENCE_BASE_URL (Confluence) "
            "and/or SLACK_WEBHOOK_URL / SLACK_BOT_TOKEN (Slack) in .shepitnoterc. "
            "Nothing to publish.",
            file=sys.stderr,
        )
        return 0

    overall, results = run_all(summary_file, publishers, runner, marker_present)
    for name, code in results:
        if code == DEFERRED:
            status = "deferred (Confluence not ready; will retry)"
        elif code == 0:
            status = "ok"
        else:
            status = f"FAILED (exit {code})"
        print(f"publish: {name} -> {status}", file=sys.stderr)
    return overall


if __name__ == "__main__":
    sys.exit(main())
