# Measuring the benefit

## The roster case

**Funnel Hacking AI ("The Optimizer"):** `+20%` direct-booking conversion
(revenue). "Tracks conversion at each stage of the direct-booking funnel
(visit, search, inquiry, booking) and prices every leak in euros, so you
know which step is worth fixing first. Then it fixes it: rewrites headlines,
images, and calls-to-action, A/B tests the change live, and rolls out only
statistically significant winners." Output: "Conversion-optimisation
programs typically lift booking conversion 10–30% over time."

These are the roster's own figures, not this repo's promise on top of them.
Two honest notes on the "rewrites" verb: this repo describes a change for a
person to implement in your own CMS or A/B testing tool - it never patches
your live site itself (see `docs/how-it-works.md` and the family scope note
in `docs/integrations.md`); and the engine never writes the copy itself -
every variant comes from `config/agent.yaml: experiment_catalog:`, written
by a person (see "Design decisions" #2).

## What `make report` shows

```bash
make report
python3 tools/report.py --json
```

- **Total proposals and decisions seen**, and **by kind**
  (`experiment_start`, `experiment_decision`) - volumes, from
  `data/agent.db`, nothing phoned home.
- **Waiting for a person** - the queue depth right now.
- **Tests started** - how many `experiment_start` items were approved and
  sent (a real staff notification went out, or would have in live mode).
- **Winners pushed** and **Dismissed** - the outcome of every scored
  decision.
- **Discarded before starting** - proposals a human rejected outright,
  before a test ever ran.
- **Proposal copy changed by a human before starting** - every
  `tools/review.py edit` is recorded; a pattern here (the same catalog
  entry edited the same way repeatedly) is a signal to update
  `config/agent.yaml`'s catalog text itself, not to keep overriding by
  hand.
- **LLM calls and spend** - narration only. The one prompt in this repo
  never decides a bottleneck or a winner, so this line should stay very
  small even at volume; a spend spike here almost always means the LLM
  provider is being called for something outside this repo's own one task.

## Reading these numbers honestly in shadow mode

While `mode: shadow` (the default, and where every fresh clone starts),
nothing was actually sent to staff or a sheet - "tests started" and
"winners pushed" describe what a human approved in the review queue, not
what left the building. Do not quote either number to anyone as a
completed action until `workflows/90-go-live.md` has been worked through -
at that point the same numbers mean what they say.

## Caveats worth keeping in mind

- **The projected euro figure is a model, not a measurement.**
  `projected_monthly_eur()` assumes new clickers convert at only half of
  today's rate (`economics.marginal_factor`) - deliberately conservative,
  but still a projection of what fixing a leak to its benchmark floor could
  be worth, not what your booking engine later shows as booked revenue.
- **The measured euro figure depends on your own testing tool's daily
  export being accurate.** `measured_monthly_eur()` is a real calculation
  on the numbers in `funnel_experiment_daily.csv` - it is only as honest as
  that CSV.
- **The benchmark bands are hotel numbers with no universal truth.**
  `benchmarks.click_low_pct` / `click_high_pct` and the search-to-booking
  band are defaults, not laws of nature - re-source them from your own
  property's history, and definitely re-source them if you are running the
  restaurant lens (`docs/how-it-works.md` "Restaurant lens").
- **SEO stays inert on purpose.** `seo_keywords` is shown in the digest,
  never turned into a proposal - see "Design decisions" #12. Do not expect
  a ranking movement to show up here as an experiment.
- **A short review history is not a track record.** A few weeks of shadow
  mode tells you whether the catalog and the benchmarks make sense for this
  property; it does not tell you what a season of live testing would have
  earned. Go live deliberately, and keep watching `make report` after you
  do.
