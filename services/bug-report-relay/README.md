# BetterFingers bug-report relay

This is the server-side trust boundary for automatic in-app bug reports. It is
designed for Cloudflare Workers and has no runtime dependencies. It can send a
reviewed report to a private Discord support channel or a support email inbox.

It is **not live merely because this directory exists**. Direct delivery stays
off in the desktop app until an operator deploys this Worker, configures its
server-side secrets, verifies both destinations, and sets the packaged app's
relay URL and enabled channels.

## Security contract

- Only `POST /report` is accepted. Browser-origin requests, compressed bodies,
  unknown fields, invalid UTF-8, and requests over 40 KiB are rejected.
- The report is revalidated against the same closed schema the desktop builds.
  A caller cannot add raw logs, paths, transcripts, arbitrary attachments,
  webhook URLs, or provider credentials.
- A Cloudflare Rate Limiting binding is mandatory. Requests without Cloudflare
  edge identity are rejected outside explicitly enabled local development.
- A KV binding records only channel, report ID, and delivery state. It stores no
  report content and suppresses ordinary duplicate submissions for seven days.
- Provider secrets remain Worker secrets. They never enter a response, log,
  desktop package, preload bridge, renderer, or report payload.
- Discord delivery disables every mention type and attaches the exact reviewed
  JSON. Email delivery uses plain text and Resend's idempotency header.
- Responses contain only a correlation ID, channel, and coarse status. The
  Worker intentionally has no report-content logging calls.

The rate limiter is an abuse brake, not authentication. A desktop binary cannot
safely hold a shared API secret: extracting it would turn every install into a
spam credential. Keep the destination private, monitor provider volume, and add
Cloudflare WAF/Bot controls before broad public distribution.

## Configure

1. Install a current Wrangler release (the Rate Limiting binding requires
   Wrangler 4.36.0 or newer).
2. Copy `wrangler.toml.example` to `wrangler.toml`.
3. Create production and preview KV namespaces and replace the placeholder IDs.
4. Choose an account-local positive integer for the rate-limit `namespace_id`.
5. Add only the destinations you will support:

   ```powershell
   npx wrangler secret put DISCORD_WEBHOOK_URL
   npx wrangler secret put RESEND_API_KEY
   npx wrangler secret put BUG_REPORT_EMAIL_TO
   npx wrangler secret put BUG_REPORT_EMAIL_FROM
   ```

   `BUG_REPORT_EMAIL_TO` and `BUG_REPORT_EMAIL_FROM` must be plain email
   addresses. The Resend sending domain must already be verified. The Discord
   webhook should point to a private support channel with tightly limited
   membership and retention.

6. Run `npm test`, then deploy with `npx wrangler deploy`.
7. Check `GET /health`. It returns destination/binding booleans, never secrets.
8. Send one reviewed synthetic report to each enabled destination and confirm it
   arrives exactly once. Delete the synthetic report afterward.
9. Configure Electron main at package/runtime launch:

   ```text
   BETTERFINGERS_BUG_REPORT_ENDPOINT=https://YOUR-WORKER.example/report
   BETTERFINGERS_BUG_REPORT_CHANNELS=discord,email
   ```

Do not add provider secrets to those desktop variables. The endpoint must be a
public HTTPS URL without credentials, query parameters, fragments, or an
explicit non-443 port.

## Local verification

`npm test` uses injected rate-limit/KV/provider fakes and makes no network calls.
For `wrangler dev`, put `ALLOW_LOCAL_REQUESTS=true` in `.dev.vars`; never commit
that file and never enable the bypass in a deployed environment.

## Operations and retention

- KV keeps only `processing` for 10 minutes or `delivered` for seven days.
- Report content is retained only by the chosen Discord/email provider. Set and
  publish a support retention period before enabling direct delivery.
- Restrict provider and Cloudflare access to support operators; rotate a webhook
  or API key immediately if it leaks.
- Monitor 429, 502, and provider-volume trends without logging request bodies.
- Treat a `202 accepted` as provider acceptance, not a promise of a human reply.
- During an incident, disable the affected destination by removing its Worker
  secret and remove that channel from the desktop configuration.

References: [Cloudflare Rate Limiting bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/),
[Discord webhook execution](https://docs.discord.com/developers/resources/webhook), and
[Resend send-email API](https://resend.com/docs/api-reference/emails/send-email).
