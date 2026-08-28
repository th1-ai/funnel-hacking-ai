# Workflow: troubleshooting

Read the whole error before doing anything - every tool here is written to
say what broke and what to do about it. If you fix something not covered
below, add it here.

## `make doctor` shows a FAIL

Each `FAIL` line has a `->` fix hint right under it. Common ones:

- **`hotel identity`: name is still 'Hotel Aurora'.** Expected on a fresh
  clone. Edit `config/hotel.yaml`.
- **`experiment catalog`: config/agent.yaml has no experiment_catalog.**
  This agent never invents copy - add at least one row (see
  `config/agent.example.yaml`).
- **`llm provider`: claude-code selected but `claude` is not on PATH.**
  Install Claude Code, or switch `llm.provider` to `interactive` or
  `anthropic` in `config/hotel.yaml`.
- **`llm provider`: ANTHROPIC_API_KEY is not set.** Add it to `.env`, or
  switch `llm.provider` to `claude-code` or `interactive`.
- **An adapter shows FAIL, not warn.** `universal`/`built` adapters fail
  loud when misconfigured (`warn` is reserved for stubs). Read the `detail`
  column - it names the missing file or variable. PMS and email always show
  `ok` on the bundled mock fixtures; this agent does not use either, see
  `docs/integrations.md`.

## `make demo` does not print `DEMO OK`

- Make sure `make setup` ran first (`.venv` must exist).
- `tools/demo.py` forces `llm.provider=mock` and reads
  `fixtures/inbound/*.csv` - if you deleted or renamed those files, restore
  them from git.
- Read the traceback if there is one; `tools/demo.py` does not swallow
  errors on purpose, so a fixture problem shows up immediately.

## `make run` exits with code 3

Not an error. `llm.provider: interactive` parked the growth-note prompt.
Read `data/pending/*.prompt.md`, write your answer to the matching
`*.answer.json` (JSON only, matching the schema shown, no prose, no code
fence), and run the same command again - every proposal and decision it
already queued is not recomputed.

## A page in my catalog never gets proposed

Two honest reasons, both by design, neither a bug:

1. Its `site_pages` click-through is already at or above its own benchmark
   - `make doctor`'s "signal sources" line confirms which file is feeding
     that page's numbers.
2. The `(page_slug, element)` pair already has a running or undecided test
   - `python3 tools/review.py list --kind experiment_start` and `--kind
     experiment_decision` show what is occupying it.

## No decision ever appears for a running test

`data/imports/funnel_experiment_daily.csv` needs at least
`min_days_running` (14 by default) distinct `day_offset` values for that
exact `(page_slug, element)` pair. `make doctor`'s "signal sources" line
shows whether that file is even being read yet.

## An item is stuck at `sending`

A process died between claiming an item and finishing the send.
`tools/run.py` calls `core.store.Store.reap_stuck_sending()` on every pass,
which moves anything stuck for more than 30 minutes to `failed` so you see
it in the queue instead of it vanishing. Use
`python3 tools/review.py retry <id>` once the cause is fixed.

## `python3 tools/*.py` says `ModuleNotFoundError: No module named 'core'`

You ran it with a Python that is not the repo's virtualenv, or from outside
the repo root. Use `make run` / `make doctor` / etc. (they call
`.venv/bin/python` for you), or run `.venv/bin/python tools/run.py` directly
from the repo root.

## Still stuck

`data/logs/*.jsonl` has every decision the agent made, in order, with a run
id. `python3 tools/review.py show <id>` has the full event trail for one
item. If neither explains it, that is a real bug - describe exactly what
you ran and what you expected, and ask.
