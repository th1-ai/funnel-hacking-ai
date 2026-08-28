# Workflow: the daily funnel analysis

Objective: read the funnel, rank the leak in euros, and propose the day's
experiment ideas from the catalog. This is Funnel Hacking AI's main job -
Track A of `docs/how-it-works.md`. Track B (scoring running experiments)
happens in the same pass; see `workflows/15-experiments.md`.

## Steps

1. **Check the agent is healthy.**
   ```bash
   make doctor
   ```
   A `FAIL` on "experiment catalog" means `config/agent.yaml` has no
   `experiment_catalog:` rows - fix that first, this agent has nothing to
   propose without one.

2. **Run one pass.**
   ```bash
   make run                              # analyze + propose + score
   make run ARGS="--dry-run"             # compute everything, queue nothing
   make run ARGS="--as-of 2026-09-15"    # rehearse against a specific date
   ```
   If `llm.provider` is `interactive`, the pass finishes the real work first
   (nothing about the analysis or the proposals waits on the model) and then
   stops with exit code 3 while it waits for you to write the growth note.
   Read `data/pending/*.prompt.md`, answer into the matching
   `*.answer.json`, and re-run the same command - the proposals already
   queued are not recomputed. (Through `make run`, the console prints
   `make: *** [run] Error 3` - Make's own exit status for any failed recipe
   is always 2, whatever the command underneath actually returned; see
   `workflows/99-troubleshooting.md`.)

3. **Read what it did.** Every pass prints its own thinking log, one line
   per step: the funnel read top to bottom, each stage judged against its
   benchmark, the biggest leak ranked in euros, how many tests are running,
   and how many changes were proposed (and how many suppressed, and why).
   Summarise this for the user in plain language - what's leaking, what got
   queued, what got left alone on purpose.

4. **Show what is waiting.**
   ```bash
   make review
   python3 tools/review.py show <id>
   ```
   For an `experiment_start`, `show` prints the projected euro value, any
   brand-voice note, and whether it is blocked at the concurrency cap. Read
   the reason back to the user in plain language - do not paste raw JSON at
   them.

5. **Act on their decision.**
   ```bash
   python3 tools/review.py approve <id>                  # start the test as proposed
   python3 tools/review.py edit <id> --variant-b "..."    # tweak the copy first
   python3 tools/review.py reject <id> --reason "not this quarter"
   ```
   Then send what was approved:
   ```bash
   python3 tools/review.py send
   ```
   In `mode: shadow` this always reports "blocked... nothing leaves in
   shadow mode" - that is the point. Nothing starts until
   `workflows/90-go-live.md` has been worked through. When it does send, the
   write is `messaging.notify_staff()` - a plain-text instruction for a
   person to actually implement in your CMS or A/B testing tool. This repo
   never touches your website.

6. **Report.**
   ```bash
   make report
   ```

## Edge cases

- **A page in the catalog is not proposed.** Either its click-through is
  already at or above its own benchmark (nothing to fix - see
  `docs/how-it-works.md` "Design decisions" #5), or the `(page_slug,
  element)` pair is already the subject of a running or undecided test (see
  `workflows/15-experiments.md`).
- **A blog-page proposal never shows up.** `rules.seo_watch` is off. Turn it
  on in `config/agent.yaml`, or read the "Deliberately left alone" line in
  the thinking log for the reason.
- **A held item you never look at.** `store.mark_stale()` runs every pass
  and ages anything sitting in `pending_review`/`needs_human` for more than
  72 hours to `stale`. Revive it with `python3 tools/review.py show <id>` -
  a human can move a `stale` item back with `approve`/`edit`/`reject`.
- **`funnel_daily.csv` or `site_pages.csv` is missing.** The analysis still
  runs, on zero rows, and says so honestly in the thinking log rather than
  guessing. `make doctor`'s "signal sources" line shows exactly which file
  each signal is reading from.
