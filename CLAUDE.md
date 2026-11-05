# Axella – notes for Claude

## Workflow – strictly in this order, every change, no exceptions

1. **Request** – work starts from a product feature request (Axella project, `claude/dev-request-*.md`) or a review /
   test finding. No request, no code. Say which request you are working on.
2. **Development** – build it on the working tree. **Do not commit.**
3. **Test** – `tools/run-tests.sh` (all of `setup/tests/`, the intake test, `web/tests/*.mjs`) and the dashboard build
   (`cd web && npx tsc -b`). Fix until everything passes. Live checks (`setup/live-checks/`) and browser tests are for
   the owner to run on the Mac mini – list the ones that apply. Then `python3 tools/pii-check.py --tree` and show
   its result line in the handover – a hit is fixed with invented values, never added to the allow list unless it is
   the owner's own deliberate text (LICENSE, README credits).
4. **Security check** – stop and hand over to the security agent (the owner starts it). It reviews the change and,
   only when no P1/P2 is open, writes the stamp with `tools/security-stamp.sh`. Fix what it finds; any change after
   the stamp needs a new check. Never write or touch the stamp (`.git/axella-checks/`) yourself.
5. **Git check** – `tools/release-check.sh --tree`: no real data (`tools/pii-check.py`: your own data in `state/` and
   config, both blocklists, made-up e-mail domains and numbers), no secrets, nothing from the never-commit paths below.
6. **Commit** – only now, everything at once (`git add -A`), a plain `git commit`. The pre-commit hook
   (`tools/hooks/pre-commit`, switched on with `git config core.hooksPath tools/hooks`) checks 3, 4 and 5 again and
   refuses otherwise. Never `--no-verify`, never `--amend`, never change `core.hooksPath`, never commit "to save work".
   If the hook refuses, fix the cause – don't work around it. Pushing is the owner's decision.

## Rules

- Read docs/DEVELOPMENT.md for the layout. AXELLA.md is the contract with the scheduled digest runs – change the digest/JSON
  format there and in `web/src/lib/types.ts` together.
- Hard rules: no send or permanent-delete action anywhere; forwarding only receipts to the closed recipients list
  (forwarding.py). Claude runs (setup/scheduler.py) get a read-only tool allow-list. "Delete" = move to Trash; file delete = move to
  `state/project-files/.deleted/`. AppleScript gets user data only as argv.
- Both servers bind 127.0.0.1 only and accept connections only from Tailscale's process (`peer_is_tailscale`); never
  open a port to the network or weaken that check. Identity comes from Tailscale Serve headers.
- POSTs to the action service need `X-Axella: 1` + JSON (except `project_upload`, raw body, allow-listed types).
- NEVER real user data in source code, comments, tests, prompts (`setup/local-tasks/*.md`), help text, placeholders,
  fixtures or commit messages – not names, places, dates, booking references, flight or ticket numbers, mail subjects,
  addresses, phone numbers or amounts taken from mail, screenshots, `state/` or anything the owner shows. Every example
  is invented from scratch (the fictional cast: Alex Example, Acme, Lee Chen, Sam Rivera, Robin, Kim, Jamie,
  Anna Keller, "+45 00 00 00 0x"; made-up places and dates). Reproducing a reported bug means rebuilding it with
  invented data, never copying the real case. E-mail addresses only in `example.com/org/net`, `*.example`, `*.test`,
  `*.invalid` or `example-*.<tld>`; long numbers look made up (555…, 0000, 1111, 12345678). `tools/pii-check.py`
  compares every file with the owner's data and is a safety net, not the check – read the diff. Real values live
  only in the local, git-ignored `tools/public-release/blocklist.local.txt` and `pii-allow.local.txt`.
- Never commit anything from `digests/`, `state/`, `calls/` or `contacts.md` (personal data,
  protected-workplace content, push keys). Your own `AXELLA.md` and `setup/actions-config.json` are not in git either –
  the repo has `AXELLA.example.md` and `setup/actions-config.example.json`.
- Python on the Mac mini is `/usr/bin/python3` (3.9) – no 3.10+ syntax.
- Dashboard look and motion follow the Axella design system (project docs / artifact): tokens in `web/src/index.css`,
  icons only via `@/components/ax-icons`, dawn only for urgent/overdue, rows ≥ 44 px, honour Reduce Motion.
- `knowledge/` (entries) is personal data like `state/` – never commit it. Runs only read it.
- New item actions go through `ActionBar` in `ItemRow.tsx`, which also hands them to the iPhone swipes (`useRowSwipe`,
  `lib/rows.ts`) – keep the two in step.
- Guided tours (`web/src/components/Tour.tsx` TOURS) point at `data-…` markers on the screens: a change to a screen with
  a tour (Today, the header and menu, Trips, Meetings and a prep, Calendar, a project, Settings → System) keeps its markers
  or updates the tour's steps. `node web/tests/tour-anchors.test.mjs` (in run-tests) checks the markers; walk the tours
  with `web/tests/tours.cjs` by hand. Tours only point – never an action, a sheet or a call to the Mac mini.
- Dashboard: `cd web && npm run deploy`. Action service: restart with launchctl after changing `setup/*.py`.
- The web root and access list live outside this repo in `../www/` (see README).
