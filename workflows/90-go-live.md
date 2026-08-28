# Workflow: shadow to live

Objective: decide, together with the hotel, whether Funnel Hacking AI is
ready to actually notify staff and log decisions on its own instead of only
queuing them - and make the change safely if so.

This is the hotel's decision, never the agent's. Do not suggest it until the
checklist below is genuinely true, and when you do raise it, say plainly
what changes. "Going live" here never means this repo starts editing your
website - it never does that, in any mode. It means an approved item's
`messaging.notify_staff()` (and, for a decision, `sheets.append()`) actually
fires instead of being recorded and held.

## Checklist

- [ ] `make doctor` is clean (no `FAIL` lines). `warn` on `mode` is expected
      until you flip it.
- [ ] `config/hotel.yaml` has the real property name, currency and contact
      details.
- [ ] `config/agent.yaml`'s `experiment_catalog:` holds your own test ideas,
      not just the shipped examples - unless you genuinely want to start
      with those.
- [ ] At least a few real `make run` passes have gone through the review
      queue against your own `data/imports/funnel_daily.csv` and
      `site_pages.csv`, not just the bundled fixtures.
- [ ] The hotel has read a handful of proposals and decisions and trusts
      the numbers - the benchmark bands and `economics:` assumptions in
      `config/agent.yaml` are honest for this property (doubly true if this
      is the restaurant lens - see `docs/how-it-works.md` "Restaurant
      lens", the hotel bands do not transfer).
- [ ] A real messaging adapter is connected (`systems.messaging.adapter:
      unipile` or `webhook`) and `make doctor` shows it healthy - going
      live on `mock` would only ever write to `data/exports/`.
- [ ] Run `python3 tools/review.py stale` once, right before the flip - it
      clears anything that piled up during shadow mode, which was never
      sent and may no longer be current.

## Making the change

1. Edit `config/hotel.yaml`:
   ```yaml
   mode: live
   ```
2. `review.require_approval_for` still lists `send_message` and
   `sheets_write` by default - it should. Going live means **approved
   items actually notify staff**, not that the agent starts anything
   unapproved. `rules.auto_rollout` in `config/agent.yaml` staying `false`
   is a second, independent brake - see below.
3. Run `make doctor` again to confirm.
4. Run one real pass and manually watch a send go through:
   ```bash
   make run ARGS="--limit 1"
   python3 tools/review.py list
   python3 tools/review.py approve <id>
   python3 tools/review.py send
   ```
5. Tell the hotel exactly what just changed: an approved item now really
   notifies staff (and, for a decision, logs to a sheet) the next time
   someone runs `python3 tools/review.py send` - still never automatic
   before that approval.

## Turning on `rules.auto_rollout` (optional, and separate from going live)

Even in `mode: live`, a decision only auto-publishes itself if **all** of
these are true: `rules.auto_rollout: true` in `config/agent.yaml`, the
95% significance bar and positive-lift gate both pass, the lift is under
`big_swing_pct`, **and** you have removed `send_message` and
`sheets_write` from `review.require_approval_for` in `config/hotel.yaml`.
That is a deliberate, separate decision from going live - most hotels
should run live with `auto_rollout` off for a while first, and read
`docs/safety.md` before turning it on.

## Going back to shadow

```yaml
mode: shadow
```
in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env` for one run.
Either stops every outbound action on the next pass, mid-schedule, with no
other change required.
