# Bug reporting

BetterFingers has an in-app, review-first bug-report flow in **Utilities → Diagnostics → Report a Bug**.
It is deliberately separate from **Copy Support Report**. The support report is a richer manual artifact;
it includes details that are useful to a person after review but are too identifying for automatic delivery.

## User flow

1. The user describes the bug, reproduction steps, expected behavior, actual behavior, and optional contact.
2. Electron main—not the renderer—fetches `/diagnostics/support-report` from the authenticated local sidecar.
3. Main creates a closed, coarse diagnostic projection and a frozen preview that expires after 10 minutes.
4. The user reviews the exact preview and checks an explicit consent box.
5. Main shows a native system confirmation before any network, clipboard, or external-navigation action.
6. A configured HTTPS relay can acknowledge automatic delivery. Without a relay, BetterFingers copies the
   report and opens the user's email client or the BetterFingers Discord invite. Opening an app is reported as
   a handoff, never as a completed submission.

The renderer can submit only a preview ID and one fixed destination. It cannot attach logs, diagnostics, an
endpoint, credentials, or a replacement payload.

## Automatic diagnostic schema

The automatic projection is a closed allowlist. Unknown current or future fields are omitted.

Included:

- report/schema ID and timestamps;
- BetterFingers backend and configuration schema versions;
- platform family and Python major/minor;
- coarse hardware tier and a GPU-acceleration capability flag;
- LLM/STT/TTS readiness booleans, bounded runtime build/timing values, and fixed error codes;
- resident model count, without model names or IDs;
- recent runtime error counts grouped by fixed severity and component; and
- at most 15 chronological error breadcrumbs containing only timestamp, allowlisted component/severity, and a
  code when the backend message is itself a bounded machine identifier (no spaces or free-form text).

Never included automatically:

- transcripts, drafts, prompts, generated text, Message Rescue content, or persona examples;
- audio, recordings, wake phrases, screenshots, or clipboard contents;
- raw/debug logs or exception/error messages;
- filesystem paths, environment values, usernames, or network-share paths;
- exact CPU/GPU names, serial-like identifiers, memory totals, or driver details; or
- model IDs, provider/account names, or model storage paths.

User-entered bug fields are content-bearing. They are included only because the exact report is previewed and
the user explicitly consents to that report.

## Relay configuration

Automatic delivery is disabled unless both variables are present in the Electron main-process environment:

- `BETTERFINGERS_BUG_REPORT_ENDPOINT` — a public HTTPS relay URL.
- `BETTERFINGERS_BUG_REPORT_CHANNELS` — comma-separated `discord`, `email`, or both.

The client rejects HTTP, credentials in URLs, query strings, fragments, non-443 explicit ports, localhost,
private/link-local IP literals, and direct Discord webhook URLs. The endpoint is never exposed to the renderer.

No relay endpoint is deployed or configured by this repository change. Until an operator deploys one, the app
offers only the honest clipboard-plus-email/Discord handoff.

The deployable implementation is in `services/bug-report-relay/`. It is a dependency-free Cloudflare Worker
with a mandatory Rate Limiting binding, KV delivery-state deduplication, strict origin/body/schema guards,
Discord mention suppression plus an exact JSON attachment, optional Resend plain-text email delivery, and
content-free correlation responses. Its README is the deployment and operations runbook.

### Request contract

The relay receives a JSON `POST` with no client-held secret:

```json
{
  "schema_version": 1,
  "channel": "discord",
  "report": {
    "schema_version": 1,
    "report_id": "uuid",
    "created_at": "ISO-8601 timestamp",
    "privacy_note": "constant explanatory text",
    "bug": {},
    "automatic_diagnostics": {}
  }
}
```

The client requires both a 2xx status and a bounded JSON acknowledgement whose channel matches the request:

```json
{
  "ok": true,
  "status": "accepted",
  "channel": "discord",
  "request_id": "content-free correlation id"
}
```

`status` may also be `duplicate` when this exact report/channel was delivered earlier. A generic 2xx page,
malformed JSON, wrong channel, redirect, timeout, or network failure is shown as unconfirmed; the client never
claims the report was sent. The reference ID is shown to the user after a confirmed acknowledgement.

### Relay requirements

The relay is the trust boundary for third-party credentials and must:

- keep Discord webhook/bot tokens and email-provider/SMTP credentials server-side;
- validate the exact schema and reject unknown fields, oversized requests, redirects, and unsupported channels;
- enforce rate limits, deduplication by `report_id`, abuse controls, retention limits, and access logging that
  does not duplicate report content;
- format Discord messages with `allowed_mentions: { "parse": [] }` and prevent user/role/everyone pings;
- escape or safely render all user-entered text;
- keep optional contact data out of public replies and public channels where possible;
- return 2xx only after durable acceptance, not merely after parsing the request; and
- document deletion, access, retention, and incident-response policy before production use.

The included Worker keeps only `processing` (10 minutes) and `delivered` (seven days) state in KV; report
content is retained only by the configured Discord/email provider. Before production use, the operator must
set a public retention policy, restrict provider access, and verify the destination channel/inbox is private.

Do not put a Discord webhook, bot token, SMTP password, email API key, bearer token, or signed secret in the
desktop package, preload bridge, environment variables shipped to users, logs, or renderer IPC. Packaged client
code is inspectable; embedding a secret would turn every installation into a reusable spam credential.

## Verification

Focused checks live in:

- `app/tests/bugReportController.test.mjs`
- `app/tests/bugReport.test.mjs`
- `app/tests/bugReportIntegration.test.mjs`
- `services/bug-report-relay/test/index.test.mjs`

The controller tests inject paths, identifiers, content-bearing errors, unknown fields, Discord mentions, bad
endpoints, timeouts, and failed deliveries to prove the automatic payload fails closed and the UI remains honest.
