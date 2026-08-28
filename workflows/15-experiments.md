# Workflow: scoring and shipping a running experiment

Objective: once a test you started has real daily results, decide whether
to ship the winner. This is Track B of `docs/how-it-works.md`, and it runs
inside the same `tools/run.py` pass as `workflows/10-funnel-analysis.md` -
there is nothing extra to schedule.

## Steps

1. **Log your testing tool's daily results.** Whatever tool you implemented
   the test in (a CMS's own A/B feature, Optimizely, VWO, Google Optimize,
   or a hand-rolled split) exports or lets you export a daily per-arm
   report. Append it to `data/imports/funnel_experiment_daily.csv` -
   columns `page_slug, element, day_offset, variant, sessions, clicks,
   bookings`, one row per arm per day. `day_offset` just needs to count
   distinct days; it does not have to be a calendar date.

2. **Run a pass.**
   ```bash
   make run
   ```
   Once a running `(page_slug, element)` pair has at least
   `min_days_running` (14 by default) distinct days of data, this pass
   scores it: a real two-proportion z-test on click-through, plus a
   booking-rate lift, and queues one `experiment_decision` item. Fewer days
   than that, and the pass does nothing for that pair - try again once more
   data has arrived.

3. **Read the decision.**
   ```bash
   python3 tools/review.py show <id>
   ```
   Prints the click-through move, the confidence, the z-score, the booking-
   rate move, and the measured monthly euro impact. Explain it in plain
   language: did B beat A, by how much, and how sure are we.

4. **Decide.**
   ```bash
   python3 tools/review.py approve <id>   # Approve and push
   python3 tools/review.py reject <id> --reason "not worth it"   # Dismiss
   ```
   Approving and sending (`python3 tools/review.py send`) writes
   `messaging.notify_staff()` **and** `sheets.append("experiment_decisions",
   …)` - the instruction to make variant B the new control, plus the
   permanent record of why. Rejecting is "Dismiss": the control stays, and
   the reason is logged on the item.

5. **Report.**
   ```bash
   make report
   ```
   Shows tests started, winners pushed, and dismissals.

## The gates, and what to expect

- **Both significance AND direction are required.** `rules.significance_95`
  (95% by default) and a positive click-through lift both have to hold -
  see `docs/how-it-works.md` "Design decisions" #3. A variant that is
  significantly *worse* never clears the gate, whatever the rule says.
- **A big swing always waits for a person.** `big_swing_pct` (25% by
  default) in `config/agent.yaml` - a click-through lift past it is never
  auto-published, whatever `rules.auto_rollout` says. Expect to see this
  fire in the bundled demo: the seeded homepage test has a very large lift
  on purpose, to prove the rule works.
- **`rules.auto_rollout` (off by default).** On, a significant, positive,
  non-big-swing decision attempts to publish itself in the same pass - but
  it still goes through `core.review`'s write guard, so `mode: shadow`
  blocks it exactly like everything else, and in `mode: live` it is blocked
  too unless you have also removed `send_message` and `sheets_write` from
  `review.require_approval_for` in `config/hotel.yaml`. Read
  `workflows/90-go-live.md` before turning this on.
- **The 2-test concurrency cap applies to starting, not scoring.** Scoring
  and deciding a test that is already running never counts against the cap
  - only `tools/review.py approve` on a fresh `experiment_start` checks it.
