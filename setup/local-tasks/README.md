# Local task prompts

Prompts for the runs the Mac mini starts itself (setup/scheduler.py, inside the action service).
One file per task; the file name is the task name. Each is passed as-is to `claude -p`, with the Axella folder
as working directory, `state/mcp.json` (Macuse) as the only MCP server and a read-only tool allow-list.
Behaviour belongs in AXELLA.md and contacts.md – change these files only for task-specific steps.

Exception: `feedback-summary.md` (Sundays 20:00, only when `setup/feedback_pull.py` brought in new axella.dev form
entries) runs on Sonnet in its own scratch folder with a copy of `feedback/` – no MCP servers, no web, no shell, no
access to the Axella or home folders – and may write only `feedback/summary.md`. Every other run is refused
`feedback/inbox/`. Its last line goes to `state/feedback-line.json` for the Sunday week-ahead.
