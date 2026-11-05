# Report a problem

Cmd/Ctrl+B anywhere (or account menu → Report a problem, or a long press on the Axella mark on the phone) opens a short
form: what happened or what's missing, a kind (Critical · Annoying · Cosmetic · Missing – Axella suggests one), and a
privacy render of the screen. Every report is saved on the Mac mini first (Settings → Reports); sending is a separate
tap after a full preview of exactly what leaves.

## Two modes (`"reports"` in setup/actions-config.json)

| | developer | community (default) |
|---|---|---|
| who | your own instance, for developing Axella | everyone else |
| kept | `reports/<id>/` – report.json, the privacy render **and the real screen** | `reports/<id>/` – report.json and the privacy render |
| sent | nothing – the development thread reads `reports/` | the anonymised payload to the intake (default `https://axella.dev/api/report`) |
| extra | Settings → Reports → Community reports: triage (needs `state/report-triage-token`) | a code and status link per report |

`reports/` is not in git, is `0700`, and no Claude run may read it (scheduler denies).

## What the anonymised payload holds – an allow-list, not scrubbing

- **class** and the **text you typed** – checked on the Mac mini before sending: e-mail addresses, phone numbers,
  card/IBAN-like numbers, links with a path, and names from your contacts and recent digests are highlighted ("This
  looks personal – remove it?"). You decide.
- **route** (the screen's name), **trail** (the last action names, e.g. `open_route:today`, `act:file` – no ids, no text).
- **errors** as templates (`Failed to parse message from {text}`), only Axella's own stack frames; the Mac mini adds
  its own recent errors the same way.
- **meta**: app version, commit, OS and version, Mac model, RAM tier, connector types, theme, locale. Never host names,
  paths, accounts, ids, tokens or message counts.
- **render**: the privacy render – the page copied, every content string replaced by same-length `x`/`0`, pictures
  replaced by grey blocks; only the app's own labels (Today, Done, Before noon …) stay readable. Drawn from that copy,
  never a blurred screenshot. Optional per report.
- **install**: a random token for rate limiting (Settings can rotate it), **reply**: optional, kept apart, never published.

The same allow-list is enforced three times: `setup/reports.py` `payload()`, the intake's `src/schema.js`, and the
tests (`setup/tests/test_reports.py`, `intake/test/intake.test.mjs`).

The intake, triage and the GitHub issue bot: see `intake/README.md`.
