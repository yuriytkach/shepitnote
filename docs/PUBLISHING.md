# Publishing meeting notes

ShepitNote can publish the full notes to **Confluence** and a short **TL;DR to
Slack** — automatically after each summary via the post-summary hook, or
interactively with a confirm-before-send flow. Nothing leaves your machine until
you publish.

- [The post-summary hook](#the-post-summary-hook)
- [Guided flow: review, then confirm-gated publishing](#guided-flow-review-then-confirm-gated-publishing)
- [Confluence publishing](#confluence-publishing)
- [Slack publishing](#slack-publishing)
- [Publishing to both](#publishing-to-both)

## The post-summary hook

Set `POST_SUMMARY_HOOK` in `.shepitnoterc` to run a script after every summary is
created. The script receives the summary file path as `$1`. On success, shepitnote
writes a `.hook_done` marker so `catchup` knows not to re-run it.

```bash
# In .shepitnoterc:
POST_SUMMARY_HOOK="${HOME}/.local/bin/my-upload-script"
```

Use this to upload to Outline, Notion, a webhook, or any other destination — or
point it at one of the bundled publishers below. See `.shepitnoterc.example` for
details.

## Guided flow: review, then confirm-gated publishing

`shepitnote meeting` runs the whole loop from a single command and, unlike `full`,
**never publishes automatically** — every destination is confirmed by you first:

```bash
# Record -> review -> edit title -> confirm each publish target
./shepitnote meeting

# Optional: pre-set the title, auto-stop after 1h, pick a model/language
./shepitnote meeting -t "Sprint planning" -d 3600 -m small -l en
```

What it does, in order:

1. **Records** (stop with Ctrl+C, or `-d SECONDS`), reusing the normal record
   path — dual-track (`AUDIO_SOURCE_TYPE=dual`) meetings work here too.
2. **Transcribes and summarizes** by reusing the `process` pipeline, but with the
   automatic `POST_SUMMARY_HOOK` **suppressed**, so nothing is sent yet.
3. **Shows** the detected language, the full transcript and the generated summary
   with clear section headers (paged with `less` when interactive; plain output
   when piped or non-interactive).
4. Lets you **edit the meeting title**, written back into `<base>_metadata.json`
   so the publishers use the new value.
5. For **each configured target** (Confluence if `CONFLUENCE_BASE_URL` is set,
   Slack if `SLACK_WEBHOOK_URL` / `SLACK_BOT_TOKEN` is set) asks an explicit
   yes/no and only publishes on `yes`. A blank answer, EOF, `n`, or anything that
   is not an explicit yes means **do not publish** (fail-safe). If no target is
   configured it says so and skips publishing. When **both** are configured,
   Confluence is asked first; if you confirm Confluence but its publish fails
   (no page link produced), Slack is **skipped** rather than posting a linkless
   message that could never be back-filled with the link.

It uses plain line prompts (read from `/dev/tty`, like the title prompt during
recording) — **not** a curses TUI — so it works over a bare **SSH** session and
when stdout is a pipe. The one-shot summarization or a failed publish is surfaced
as a clear error rather than silently continuing.

> Once you have made your per-target decision, the guided flow marks the meeting
> handled (writes the `.hook_done` marker), so a later `catchup` will **not**
> re-run the automatic hook on it and override your choices — an explicit "no"
> stays "no". Your decision here is the authority for that meeting. To (re)publish
> a target afterwards, invoke its publisher under `hooks/` directly.

## Confluence publishing

ShepitNote ships a post-summary hook, `hooks/confluence_publish.py`, that converts each
summary to Confluence storage format and creates — or, on re-run, updates — a page in a
configured space (issue #3). Point `POST_SUMMARY_HOOK` at it to enable:

```bash
# In .shepitnoterc:
POST_SUMMARY_HOOK="${HOME}/path/to/shepitnote/hooks/confluence_publish.py"
```

**Configuration** (all read from the environment; `.shepitnoterc` is sourced before the hook
runs, so set them there — see `.shepitnoterc.example` for the annotated block):

| Variable | Required | Purpose |
| --- | --- | --- |
| `CONFLUENCE_BASE_URL` | yes | Wiki base, no trailing `/rest/api`. Cloud: `https://yourorg.atlassian.net/wiki`; Server/DC: `https://confluence.yourorg.com` |
| `CONFLUENCE_SPACE_KEY` | yes | Target space key (e.g. `ENG`) |
| `CONFLUENCE_API_TOKEN` | yes | Cloud API token or Server/DC Personal Access Token (never hardcoded) |
| `CONFLUENCE_EMAIL` | no | Atlassian account email; its presence selects Cloud Basic auth |
| `CONFLUENCE_PARENT_PAGE_ID` | no | Numeric parent page id; new pages are created under it and updates re-assert it |
| `CONFLUENCE_AUTH_MODE` | no | Force `basic` or `bearer`; otherwise derived from whether `CONFLUENCE_EMAIL` is set |
| `CONFLUENCE_DRY_RUN` | no | `=1` forces dry-run (same as `--dry-run`) |

**Getting a token.** On **Confluence Cloud**, create an API token at
[id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens) and set
`CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` (auth is HTTP Basic `email:token`). On **Server /
Data Center**, create a Personal Access Token in your profile and set `CONFLUENCE_API_TOKEN`
with no email (auth is `Bearer <PAT>`).

**Page title and idempotency.** The page title is `"<meeting title> - YYYY-MM-DD"`, or
`"Meeting HH:MM - YYYY-MM-DD"` when the recording had no title (both derived from the sibling
`<base>_metadata.json`, falling back to the timestamp in the filename). Because that title is
stable for a given meeting, the hook searches the space for it and **updates the existing page**
(version incremented) instead of creating a duplicate — re-running `catchup`/`process` on the
same meeting is safe. The created page id is also cached in a sibling
`<base>.confluence_page_id` marker as a fallback lookup (guards against Cloud search-index lag).

**Dry-run — preview before publishing.** Run the hook with `--dry-run` (needs no credentials)
to resolve the title and print the storage-format XHTML without touching the API:

```bash
hooks/confluence_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```

Inspect the output, then set the `CONFLUENCE_*` config and let the hook publish for real.

**Confirm-gating.** When wired to `POST_SUMMARY_HOOK`, this publisher runs automatically after
every summary — enabling it is opt-in purely by setting `POST_SUMMARY_HOOK`. If you want an
interactive **confirm before each publish** instead, use
[`./shepitnote meeting`](#guided-flow-review-then-confirm-gated-publishing): it runs the same
publisher only after an explicit per-target yes and never publishes on its own. If a publish
fails (missing config, API/network error) the hook exits non-zero, so shepitnote does not write the
`.hook_done` marker and retries it on the next `catchup`/`process`.

## Slack publishing

ShepitNote ships a second post-summary hook, `hooks/slack_publish.py`, that posts a **short**
summary of each meeting to Slack (issue #4). It runs a distinct, terser second Ollama pass over
the summary — a 3-5 bullet TL;DR plus action items, separate from the full notes — renders it as
Slack mrkdwn, appends a link to the Confluence page when one exists, and posts it via an incoming
webhook or a bot token. Point `POST_SUMMARY_HOOK` at it to enable Slack only:

```bash
# In .shepitnoterc:
POST_SUMMARY_HOOK="${HOME}/path/to/shepitnote/hooks/slack_publish.py"
```

The TL;DR pass reuses the same `OLLAMA_MODEL` / `OLLAMA_URL` as the main summary (falling back to
the same `llama3.1:8b` / `http://localhost:11434` defaults), so Ollama must be running.

**Configuration** (all read from the environment; set them in `.shepitnoterc`, which is sourced
before the hook runs — see `.shepitnoterc.example` for the annotated block). Pick **one** of the two
auth styles:

| Variable | Required | Purpose |
| --- | --- | --- |
| `SLACK_WEBHOOK_URL` | webhook mode | [Incoming webhook](https://api.slack.com/messaging/webhooks) URL; the channel is baked into it (a credential, never printed) |
| `SLACK_BOT_TOKEN` | bot mode | Bot token (`xoxb-…`) with `chat:write`; posts via `chat.postMessage` (a credential, never printed) |
| `SLACK_CHANNEL` | bot mode | Target channel for bot mode, e.g. `#meetings` |
| `SLACK_AUTH_MODE` | no | Force `webhook` or `bot`; otherwise derived from which of the above is set (both set -> webhook wins) |
| `SLACK_DRY_RUN` | no | `=1` forces dry-run (same as `--dry-run`) |

**No double-posting.** Slack messages are not idempotent (each POST creates a new message), so on a
confirmed post the hook writes a sibling `<base>.slack_done` marker and, on any later invocation,
**no-ops when that marker exists**. Because the hook is retried whenever it exits non-zero, this is
what keeps a retry from posting the same meeting twice — at most one Slack message per meeting.

**Confluence link when available.** If the Confluence publisher has already run for the meeting, it
leaves a sibling `<base>.confluence_page_id` marker; the Slack hook reads it and (with
`CONFLUENCE_BASE_URL` set) appends a `Full meeting notes on Confluence` link built as
`{CONFLUENCE_BASE_URL}/pages/viewpage.action?pageId=<id>` (works on Cloud and Server/DC). With no
marker or base URL the link is omitted gracefully and the message still posts.

**Dry-run — preview before posting.** Run the hook with `--dry-run` (needs no token/webhook) to
resolve the target and print the short summary and the exact payload without posting. It still
calls the local Ollama to build the real TL;DR:

```bash
hooks/slack_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```

The bot token and webhook URL are never printed (redacted from every error and from the dry-run
target line). As with Confluence, the hook posts whenever it is invoked; for an interactive
**confirm before each post**, use
[`./shepitnote meeting`](#guided-flow-review-then-confirm-gated-publishing), which asks yes/no per
target and never posts on its own.

## Publishing to both

There is only one `POST_SUMMARY_HOOK` slot, so to publish the **full notes to Confluence and the
short TL;DR to Slack** point it at the bundled dispatcher, `hooks/publish.py`:

```bash
# In .shepitnoterc (with the CONFLUENCE_* and SLACK_* blocks both filled in):
POST_SUMMARY_HOOK="${HOME}/path/to/shepitnote/hooks/publish.py"
```

The dispatcher runs each publisher that is configured — Confluence when `CONFLUENCE_BASE_URL` is
set, Slack when `SLACK_WEBHOOK_URL` or `SLACK_BOT_TOKEN` is set — **Confluence first**, so its page
link is available to the Slack message in the same run. Each publisher is independently idempotent
(Confluence updates the same page; Slack skips on its `.slack_done` marker), so a retry after a
partial failure re-runs only what failed and never duplicates. The dispatcher exits non-zero if any
enabled publisher failed (so shepitnote retries), and the standalone publishers remain directly
invokable for one-destination setups.
