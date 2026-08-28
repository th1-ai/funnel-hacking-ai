---
name: funnel-hacking-ai
description: Run Funnel Hacking AI ("The Optimizer") — Tracks conversion at each stage of the direct-booking funnel (visit, search, inquiry, booking) and prices every leak in euros, so you know which step is worth fixing first.. Use when the user asks to run the agent, check what is waiting for review, approve or reject a draft, or asks how the agent is doing. Trigger phrases: "run The Optimizer", "/funnel-hacking-ai", "check the queue", "what is waiting for me", "approve that draft".
---

# Funnel Hacking AI

Runs Funnel Hacking AI's daily funnel analysis and works its review queue.
Everything happens from the repo root; every command below exists and
works.

## Before anything else

Read `README.md` if you have not this session, and
`workflows/10-funnel-analysis.md` for the main loop. If the user has never
run this agent, start at `workflows/00-setup.md` instead and walk them
through it.

## The loop

**1. Check the agent is healthy.**

```bash
make doctor
```

Any `FAIL` line has a fix hint. Fix it before going further. `WARN` lines
are worth mentioning but do not stop the run — an empty `.env` or a
placeholder hotel name is expected on a fresh clone.

**2. Run one pass.**

```bash
make run                             # analyze + propose + score
make run ARGS="--dry-run"            # compute everything, queue nothing
make run ARGS="--as-of 2026-09-15"   # rehearse against a specific date
```

If `llm.provider` is `interactive`, the pass proposes and scores everything
first, then stops with exit code 3 while it waits for you to write the
growth note. Read `data/pending/*.prompt.md`, write your answer as JSON to
the matching `*.answer.json` following the schema exactly, then run the
same command again — nothing already queued is recomputed. (That "3" is
`tools/run.py`'s own exit code — `make run` prints `make: *** [run] Error
3` on screen but its own exit status is always 2, GNU Make's convention for
any failed recipe. Either way, it means the same thing: go answer the
prompt.)

**3. Show what is waiting.**

```bash
make review
python3 tools/review.py show <id>
```

For an `experiment_start`: the page, the element, both variants in plain
English, the projected euro value, any brand-voice note, and whether it is
blocked at the concurrency cap. For an `experiment_decision`: the
click-through move, the confidence, and the measured euro value, and
whether it is being held for review because of significance or a big
swing. Do not paste raw JSON at the user.

**4. Act on their decision.**

```bash
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --variant-b "New wording"   # tweak a proposal's copy
python3 tools/review.py reject <id> --reason "<why>"
python3 tools/review.py send                                   # send approved/edited
```

In `mode: shadow` (the default), `send` always reports "blocked... nothing
leaves in shadow mode" — that is correct, not a failure. Read the draft
back to the user before approving. `edit` only makes sense on an
`experiment_start` — there is nothing to edit on a decision, only approve
or reject it.

**5. Report.**

```bash
make report
```

## Rules

- **Never send in shadow mode**, and never work around a blocked write. The
  error message says what to do.
- **Going live is the hotel's decision.** Only raise it after
  `workflows/90-go-live.md` has been worked through, including
  `python3 tools/review.py stale` to clear the shadow-mode backlog first.
- **This agent never invents copy and never touches a price.** If asked to
  make either happen, say plainly that it is out of scope and point at
  `docs/how-it-works.md` "Design decisions" #2 rather than improvising.
- **This agent never edits the hotel's website.** Every send is a staff
  notification, or a sheet row — never a live page change.
- **Confirm before anything irreversible** — starting a test, pushing a
  winner — even when it is approved.
- **Never print or paste a credential.**
- If a run fails, read the whole error, fix the cause, re-run, and note
  what you learned in `workflows/99-troubleshooting.md`.
