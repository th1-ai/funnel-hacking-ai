# Guardrails and safety

This agent never talks to a guest and never touches your live website.
Everything below is built in, not optional, and this page explains what it
does and what is left for you to decide.

## The two modes

| Mode | What happens |
|---|---|
| `shadow` (default) | The agent reads, analyzes, drafts and queues. It **never** notifies staff and **never** writes to a sheet. Approving, editing or rejecting an item records your decision but sends nothing. At go-live, `python3 tools/review.py stale` clears that shadow-era queue so nothing old goes out by surprise. |
| `live` | Items you approved are really sent - a staff notification, and for a pushed decision, a sheet row. Everything else still waits. |

`mode` lives in `config/hotel.yaml`. It is a global kill switch: flipping it
back to `shadow` stops every outbound action immediately, mid-schedule, with
no other change. `config/agent.yaml` can be stricter than `hotel.yaml`,
never looser.

Two more brakes:

- `make run ARGS="--dry-run"` computes everything and writes nothing, even
  in live mode.
- `review.require_approval_for` in `config/hotel.yaml` lists the actions
  that need a human even in live mode. The defaults are `send_email`,
  `send_message`, `pms_write`, `payment`, `publish`, and (added for this
  repo) `sheets_write`. Shortening that list is how you hand the agent more
  rope, one action at a time.

Every outbound action in the codebase goes through one function,
`core/review.py:assert_write_allowed`. There is no second path.

## The review queue

Nothing starts a test, and nothing ships a winner, without passing through
the queue.

```bash
make review                        # what is waiting
python3 tools/review.py show <id>   # the full detail and how it got there
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --variant-b "New wording"
python3 tools/review.py reject <id> --reason "not this quarter"
```

Only `tools/review.py` can write `approved`, `edited` or `rejected`; only
`send` writes `sending`/`sent`. A crash between "about to send" and "sent"
is picked up on the next pass and shown to you as `failed` rather than
silently retried.

## Funnel Hacking AI's own guardrails

This agent never touches pricing and never writes to your website - the
guardrails below are what "never sent" means when the thing being decided
is a test, not an email. All are enforced in `tools/funnel_engine.py`, not
just described here - turning a rule off in `config/agent.yaml` is the only
way to change one.

- **Never touches pricing.** No field anywhere in a catalog entry, a
  proposal, or a decision can carry a rate. There is no write path to any
  price at all in this repo.
- **The engine never invents copy.** Both variants of every experiment come
  from `config/agent.yaml: experiment_catalog:`, written by a person. The
  one LLM call in this agent narrates a finished analysis - it never sees a
  bottleneck or a decision before it is final, and it never writes a
  headline or a button label. See `docs/how-it-works.md` "Design
  decisions" #2.
- **A rollout requires both significance AND a positive lift.**
  `can_publish()` checks `click_lift > 0` as well as the 95% confidence bar
  - a variant that is significantly worse can never clear the gate, in any
  configuration. See "Design decisions" #3.
- **A big swing always waits for a person.** `big_swing_pct` (25% by
  default) - a click-through lift past it is never auto-published, whatever
  `rules.auto_rollout` says. This is the concrete answer to the roster
  promise "flags big swings for review," which had no threshold in the
  system this repo was built from - see "Design decisions" #8.
- **`rules.auto_rollout` is off by default,** and even on, a decision still
  goes through the write guard above - `mode: shadow` blocks it exactly
  like a human-approved item, and `mode: live` blocks it too unless you
  have separately removed `send_message`/`sheets_write` from
  `review.require_approval_for`. See `workflows/90-go-live.md`.
- **The 2-test concurrency cap is enforced, not just shown.**
  `tools/review.py approve` on a fresh `experiment_start` counts active
  pairs and refuses outright at the cap.
- **Brand voice lock is an annotation, not a vocabulary check** - it
  attaches `brand_voice_note` from your own config to any copy proposal.
  Read it before you ship the copy; nothing here checks tone for you. See
  `docs/how-it-works.md` "Design decisions" #9.
- **The cross-agent OTA read is read-only, always.** `ota_content_findings`
  and `ota_listings` feed one informational row; this repo never writes
  either file.
- **The model is never in the numbers.** `core.llm.complete()` is called
  exactly once per pass, after the whole analysis is final, to write a
  short note. If that call fails for any reason, the run has already
  succeeded - nothing about the analysis or the proposals waits on it.

## What the agent will not do

- Notify staff or write to a sheet while `mode: shadow`, or act on an item a
  human has not approved when the action needs approval.
- Start a third test while two are already running and `rules.max_2_concurrent`
  is on.
- Take a payment, issue a refund, or move money. Payment adapters are
  read-only by design and this agent never calls one.
- Invent a page, a rate, or a euro amount that was not ingested. A signal
  with no data behind it defaults to empty, not a guess - see
  `docs/integrations.md`.

## Data handling

**What leaves your machine.** With `llm.provider: anthropic` or
`claude-code`, the prompt goes to Anthropic. That prompt contains the
finished analysis summary and up to eight proposal titles and their
pre-formatted euro value - never a guest record, because this agent has no
guest inbox. With `llm.provider: mock` or `interactive`, nothing leaves the
machine at all.

**What is stored, and where.** Everything lives in `data/` inside this
folder: `agent.db` (SQLite), `logs/*.jsonl`, `exports/`. `data/` is
gitignored. There is no cloud service behind this repo and no telemetry.

**Retention.** `privacy.retention_days` (default 365) is how long processed
items stay in the database. Deleting `data/agent.db` deletes everything the
agent knows.

## GDPR, in practice

This agent's own data is commercial, not personal: session counts,
click-through rates, page performance, experiment results. It does not read
a guest inbox and does not store guest names or contact details.

- **`funnel_daily` and `funnel_experiment_daily` hold no guest identity**,
  only aggregate counts per date, source, or arm.
- **You are the controller** for whatever this software does with your
  analytics data, same as any other repo in this family. If you use
  `llm.provider: anthropic` or `claude-code`, the only thing Anthropic ever
  sees is the finished analysis summary and a handful of proposal titles.

This is a practical summary, not legal advice.

## Drafted copy becomes guest-facing once you ship it - even though this agent never sends anything

Unlike a guest-messaging agent, this repo produces no text a guest ever
reads directly - `messaging.notify_staff()` talks to your own team, not to
a guest. The EU AI Act Article 50 guest-disclosure pattern the rest of this
family uses does not apply to anything this agent sends. But a proposal's
`variant_b` copy is written to go on your public website once a person
implements it - that is exactly what `rules.brand_voice_lock`'s note is
for, and it is worth applying your own site's general AI-content practices
to any copy that started life as one of this agent's proposals, the same as
copy from any other source.

## Subscription or API: an honest note

Two ways to pay for the reasoning:

**Your Claude Code subscription** (`llm.provider: claude-code` or
`interactive`). Flat monthly cost, no per-message billing. This is
genuinely the cheapest way to run a small hotel's agent.

The caveat, plainly: a personal Pro or Max subscription is intended for
interactive use, and Anthropic's usage policy and rate limits apply to
automated use of it. A daily scheduled run is a normal way to work.
Pointing it at a much busier schedule is not, and you will hit rate limits
at the worst moment. Read the terms and decide for yourself.

**The Anthropic API** (`llm.provider: anthropic`). Pay per token, no
ambiguity about automated use, proper rate limits, and usage you can
attribute. This is the right answer for production volume - though this
agent's one LLM call a day is genuinely light. `make report` shows what you
are spending.

Start on the subscription while you are learning what the agent does. Move
to the API only if you add more frequent scheduled passes.

## If something goes wrong

1. `mode: shadow` in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env`.
   Every outbound action stops on the next pass.
2. Remove the schedule (`crontab -e`, `launchctl unload`, or
   `systemctl disable --now <slug>.timer`).
3. `make doctor` to see what the agent thinks its state is.
4. `data/logs/*.jsonl` has every decision, with the run id, in order.
