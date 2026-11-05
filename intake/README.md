# Report intake (axella.dev)

The Cloudflare Worker that receives **community** reports from Axella's Report a problem (Cmd/Ctrl+B), keeps them in a
private queue, and – after a human look – turns them into public GitHub issues. Developer-mode reports never come here;
they stay in `reports/` on the owner's Mac mini.

```
Axella (Mac mini)  ──POST /api/report──►  Worker  ──►  D1 queue (+ R2 renders)      private
                                             ▲
maintainer's Axella (Settings → Reports → Community reports)
   ──GET/POST /api/triage (Bearer TRIAGE_TOKEN)──┘  approve ──► GitHub issue on the public repo
```

What it accepts is an allow-list (`src/schema.js`, the same as `setup/reports.py` `payload()`): class, the reporter's
text, route, action names, error templates with Axella's own stack frames, nine metadata fields, a privacy render (PNG)
and a random install token. Anything else – an extra field, a path, an e-mail in an error – is rejected, not cleaned.

Privacy: no IP address is read or stored and request logs are off (`[observability] enabled = false`); the install
token is stored only as a SHA-256 hash, for rate limiting (10 reports per install per day, 500 in all); an optional reply
address is kept in its own table and never published. A render becomes public (`/r/<id>.png`) only once its report is
approved.

## Set up (once)

```
cd intake
cp wrangler.toml.example wrangler.toml
npx wrangler d1 create axella-reports --jurisdiction eu        # put the id in wrangler.toml
npx wrangler d1 execute axella-reports --remote --file schema.sql
npx wrangler r2 bucket create axella-report-renders --jurisdiction eu   # optional
openssl rand -hex 32                                           # the triage token
npx wrangler secret put TRIAGE_TOKEN
npx wrangler secret put GITHUB_TOKEN    # fine-grained, only the public repo, Issues: read and write
npx wrangler deploy
```

On the maintainer's Mac mini: `"reports": {"mode": "developer"}` in `setup/actions-config.json`, and the same triage
token in `state/report-triage-token` (`read -s t; printf %s "$t" > state/report-triage-token; chmod 600 state/report-triage-token`).
Create the labels `critical`, `annoying`, `cosmetic`, `missing` and `from-report` on the repository once.

## Rate limit at the edge (Cloudflare WAF, once)

The per-install limit in the Worker can't stop a script that makes up a new install token for every report, so
`POST /api/report` is also limited **by IP at Cloudflare's edge**. The IP is counted by Cloudflare, never passed to
the Worker or stored, so the privacy note above still holds.

Cloudflare dashboard → the `axella.dev` zone → **Security → WAF → Rate limiting rules → Create rule**:

| Setting | Value |
|---|---|
| Rule name | `report intake – per IP` |
| If incoming requests match | Custom expression: `(http.request.method eq "POST" and http.request.uri.path eq "/api/report")` |
| With the same characteristics | IP |
| When rate exceeds | 5 requests per 10 seconds (the Free plan's shortest window; on a paid plan, 10 per 1 minute) |
| Then take action | Block, for the longest duration the plan offers |

Real users send a handful of reports a day, so this never touches them. Check: 20 quick posts from one machine – most
get HTTP 429 from Cloudflare (not from the Worker):
```
for i in $(seq 20); do curl -s -o /dev/null -w '%{http_code} ' -X POST https://axella.dev/api/report -H 'Content-Type: application/json' -d '{}'; done; echo
```
(The bodies are invalid on purpose: the first ones get 400 from the Worker, the rest 429 from the edge – nothing is stored.)

## What reaches the public issue

The reporter's text goes into the issue inside a fenced block (a fence longer than any run of backticks in the text),
with every `@` broken by a zero-width space – no live @mention, HTML, link or image. Titles get the same treatment.
Error messages may not contain backticks or `//`, renders are capped at 400 kB (the Mac mini leaves a bigger one out).

## Test

`node --experimental-sqlite test/intake.test.mjs` – runs the Worker against SQLite and a fake GitHub, no network.
