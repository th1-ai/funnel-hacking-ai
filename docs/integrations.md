# Connecting your systems

Every connector in this repo is one of three things, and the table says which.
We will not tell you an integration exists when it does not.

| Badge | Means |
|---|---|
| **built** | Written against the real API and tested against it. |
| **universal** | Works with any system through a common protocol: IMAP/SMTP, CSV, a webhook. |
| **stub** | Interface only. Calling it raises a clear error with a recipe for adding it. |

Check what is actually working on your machine at any time:

```bash
make doctor
```

**What Funnel Hacking AI actually uses.** Only two of the four core
adapters: **Messaging** (tells staff to start a test or ship a winner) and
**Sheets** (logs every winner). It does not use PMS or Email at all - see
"Signals this agent needs, with no adapter" below for where the real data
comes from instead. `pos`, `accounting`, `reviews`, `calendar`, `payments`
and `procurement` are unused stubs, same as every repo in this family.

## Status

### Messaging - `systems.messaging.adapter`

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `mock` | universal | nothing | Writes to `data/exports/sent_messages.jsonl`. What `make demo` uses. |
| `unipile` | built | your own UniPile account | WhatsApp on your own number. |
| `webhook` | universal | any URL | POST to Zapier, Make, n8n, or your own endpoint. |

**`unipile`.** You create the account, you connect your number by QR code,
you own the credentials: `UNIPILE_DSN`, `UNIPILE_API_KEY`,
`UNIPILE_ACCOUNT_ID`, `UNIPILE_STAFF_CHAT_ID`.

**`webhook`.** The simplest possible outbound: set `MESSAGING_WEBHOOK_URL`
and the agent POSTs `{chat_id, text, kind, hotel, sent_at}`. Your
automation tool delivers it however you like (Slack, email, a task board).

### Sheets - `systems.sheets.adapter`

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `csv` | universal | nothing | Writes `data/exports/experiment_decisions.csv`. |
| `google` | built | service account JSON | A live shared spreadsheet. |

For `google`: enable the Sheets API, create a service account and a JSON
key, save it as `service_account.json`, and share your spreadsheet with the
service account's email address as an Editor. Set
`systems.sheets.spreadsheet_id` to the long id from the sheet's URL.

### PMS and Email - not used

`systems.pms.adapter` and `systems.email.adapter` stay `mock` in
`config/hotel.example.yaml`. `core.doctor` checks every adapter family for
every repo in this family, so they show up in `make doctor` regardless -
nothing in `tools/` calls either one. Booking counts and revenue come from
`funnel_daily`, not from the PMS - see below.

### Everything else

`pos`, `accounting`, `reviews`, `calendar`, `payments` and `procurement` are
**stubs**: the interface exists, nothing is implemented. Calling one raises
an error that tells you exactly this.

## Signals this agent needs, with no adapter

Web analytics, a booking engine's funnel numbers, an SEO rank tracker and
an A/B testing tool's daily results are not things any common PMS, email,
messaging or sheets API exposes - there is no shared adapter family for
"a web analytics platform" the way there is for a mailbox. Rather than
pretend one exists, `tools/ingest.py` reads them straight from CSV - the
same **universal** pattern as `core/adapters/pms_csv.py`, just without
inventing a new adapter class. Each one falls back to the matching
`fixtures/inbound/*.csv` file when your own export is absent, which is what
`make demo` reads.

| File | Columns | Feeds |
|---|---|---|
| `data/imports/funnel_daily.csv` | `date, source, reach, sessions, engine_clicks, engine_searches, bookings, revenue` — `source` one of `meta_ads, google_ads, organic, direct, email, ota_referral` | the whole daily analysis (Track A) |
| `data/imports/site_pages.csv` | `slug, title, path, kind (page\|blog), sessions_30d, engine_clicks_30d, sort` | which page is the biggest leak, and what benchmark applies to it |
| `data/imports/funnel_experiment_daily.csv` | `page_slug, element, day_offset, variant (a\|b), sessions, clicks, bookings` | scoring a running experiment (Track B) - your A/B testing tool's own daily export |
| `data/imports/seo_keywords.csv` | `keyword, position, prev_position, volume, clicks_mo, url, note` | the SEO digest only - never a proposal, see `docs/how-it-works.md` #12 |
| `data/imports/ota_content_findings.csv` | `channel, kind, detail, severity` | cross-agent, read-only - the OTA-referral row's content-health note |
| `data/imports/ota_listings.csv` | `channel, health_pct, note` | cross-agent, read-only - the OTA-referral row's channel-health chips |

`make doctor`'s "signal sources" line shows which file each one is actually
reading from, or whether it is defaulting to empty. A web analytics tool
(GA4-class), your booking engine, your A/B testing tool, or an SEO rank
tracker that can schedule a CSV export into `data/imports/` plugs in with no
code changes at all - but "no code changes" is about the agent, not about
the join. Neither export below arrives shaped like `funnel_daily.csv`.
Building that one file is real, manual work the first time - the worked
example that follows is that work, done once, so you are not inventing the
join yourself.

## Worked example: GA4 + your booking engine -> `funnel_daily.csv`

Two exports, neither one enough on its own:

**GA4** (Reports -> Acquisition -> Traffic acquisition, or Explore ->
freeform, no API needed) knows sessions by channel, and, if you have set up
a custom event on your "Book now" / "Check availability" button, clicks on
it - but nothing about what happens after the visitor leaves your site for
the booking engine.

```
Date,Session default channel group,Sessions,Event count (book_now_click)
20260817,Paid Social,30,4
20260817,Paid Search,25,3
20260817,Organic Search,20,2
20260817,Direct,16,2
20260817,Email,10,1
```

**Your booking engine** (Cloudbeds, Mews, SiteMinder-class - the exact
report name varies, look for "booking engine activity" or "conversion
report") knows searches, completed bookings and revenue for the whole site,
per day - but almost never split by where the visitor came from, because
that context does not survive the handoff from your website.

```
Date,Searches,Bookings,Revenue
17/08/2026,88,26,6760
```

**The join, step by step:**

1. **Map GA4's channel names to this agent's six `source` values** (see
   `SOURCE_ORDER` in `tools/funnel_engine.py`) - GA4's default channel
   group names rarely match exactly:

   | GA4 default channel group | `funnel_daily.csv` `source` |
   |---|---|
   | Paid Social | `meta_ads` (or wherever your paid social spend goes) |
   | Paid Search | `google_ads` |
   | Organic Search, Organic Social | `organic` |
   | Direct | `direct` |
   | Email | `email` |
   | Referral (your OTA listing links) | `ota_referral` |

2. **`sessions`** = GA4 Sessions for that channel, that day. Straight copy.

3. **`engine_clicks`** = GA4's event count for your booking-button click,
   same channel, same day. If you have not wired up that event yet, do that
   first (GA4 Admin -> Events -> Create event, or ask whoever manages your
   tag manager) - without it, this agent has no way to see the
   session-to-booking-engine-click stage at all, and every projection is
   based on it.

4. **`reach`** is the loosest column, and it is fine for it to be:
   ad-platform impressions for `meta_ads`/`google_ads` if you have them
   handy, GA4 Users as a stand-in otherwise, or just left equal to
   `sessions`. `reach` only ever appears in the narrated "Read the funnel"
   line (`docs/how-it-works.md` Step 2) - it never feeds a benchmark
   comparison or a euro figure, so do not spend real effort sourcing it
   precisely.

5. **`engine_searches`, `bookings`, `revenue`** are the hard part, because
   your booking engine's report is one row a day, not six. Two ways to
   split it across sources, in order of preference:

   - **If your booking engine can export a referring-channel or UTM column**
     on searches/bookings (some can, under "attribution" or "marketing
     source" in their reporting), use that split directly - it is real data,
     not an estimate.
   - **If it cannot** (the common case), allocate the day's totals across
     sources in proportion to each source's `engine_clicks` share that day -
     the assumption being that a source sending more people into the
     booking engine also sends proportionally more of that day's searches
     and bookings. The day's totals stay exactly right either way; only the
     per-source split is an estimate.

   A day with 4+3+2+2+1 = 12 total `engine_clicks` and 88 searches / 26
   bookings / EUR 6,760 revenue splits like this under the proportional
   method:

   ```
   date,source,reach,sessions,engine_clicks,engine_searches,bookings,revenue
   2026-08-17,meta_ads,30,30,4,29,9,2253
   2026-08-17,google_ads,25,25,3,22,7,1690
   2026-08-17,organic,20,20,2,15,4,1127
   2026-08-17,direct,16,16,2,15,4,1127
   2026-08-17,email,10,10,1,7,2,563
   ```

   (`meta_ads` gets 4/12 of the day: `round(88 * 4/12) = 29` searches,
   `round(6760 * 4/12) = 2253` revenue. Round each source the same way, then
   nudge the largest share up or down by 1 if the row totals do not quite
   add back up to the booking engine's real daily total - a handful of
   arithmetic lines in a spreadsheet or a short script, not a new
   integration.)

6. **Do this once as a script, not by hand every week.** A `csv`-module-only
   Python script that reads your two raw exports and a small mapping table
   like the one above, and writes `data/imports/funnel_daily.csv` in this
   shape, is a half-day job your Claude Code session can write with you -
   ask it to read this section and `tools/ingest.py::load_funnel_daily` for
   the exact column names, then schedule that script to run before
   `tools/run.py` in your cron/launchd/systemd job (`scheduler/`).

`site_pages.csv` and `funnel_experiment_daily.csv` are simpler - both are
already one row per page or per A/B arm, no per-source join needed. The
table above has their exact columns.

## Implement your own

<a id="implement-your-own"></a>

The interface is small on purpose, and your Claude Code session can do this
with you in an afternoon. Open `claude` in this folder and paste:

> Read `docs/integrations.md#implement-your-own` and
> `core/adapters/messaging_webhook.py`. I need a messaging adapter for
> **<your system>**. Its API docs are at **<url>** and I have credentials in
> `.env` as `<VAR names>`. Copy `messaging_webhook.py` as the shape,
> implement `ping`, `capabilities`, `notify_staff` first, register it in
> `core/adapters/__init__.py`, and stop before `send` so I can check
> `notify_staff` with `make doctor`.

### The five steps

**1. Copy the closest existing adapter.** `core/adapters/messaging_webhook.py`
for a chat channel, `sheets_google.py` for a reporting target.

**2. Implement `ping()` and `capabilities()` first.**

```python
def ping(self) -> HealthCheck:
    """Never raises. Returns ok=False with a fix_hint a hotel can act on."""

def capabilities(self) -> set[str]:
    """The method names that actually do something on this adapter."""
```

`make doctor` reads both. Getting them right first means the rest of the
work has a feedback loop.

**3. Implement the reads**, if the adapter has any. Money is a float in the
hotel's currency; put anything you do not map into `.extra` rather than
dropping it.

**4. Implement the writes, each with the guard.**

```python
from core.adapters.base import guarded_write

@guarded_write("send_message")
def notify_staff(self, text: str) -> dict:
    ...
```

The decorator is not optional. Without it your adapter can write while the
agent is in shadow mode, which defeats the entire safety model. The action
name should be one of the values in `review.require_approval_for`.

**5. Register it.** One line in `core/adapters/__init__.py`:

```python
REGISTRY["messaging"]["yoursystem"] = "core.adapters.messaging_yoursystem:YourSystemMessaging"
```

Then set `systems.messaging.adapter: yoursystem` in `config/hotel.yaml` and
run `make doctor`.

### Rules that matter

- **`ping()` never raises.** It returns `HealthCheck(ok=False, ...)` with a
  hint. A broken adapter must still produce a readable doctor table.
- **Every write is decorated.** No exceptions.
- **Rate limits belong in the adapter.** Use
  `core/adapters/_http.py:RateLimiter`. Retry 429 and 5xx with backoff;
  never retry a 4xx.
- **Never log a credential.** `core/log.py` masks anything whose key looks
  like a secret, but do not rely on it.
- **Write a test.** Copy `tests/test_core_adapters_mock_csv.py`. It should
  run with no network: feed your parser a fixture, check the dataclass that
  comes out.

### `core/` is shared

`core/` is identical in all 28 agents in this family. If you change
something in `core/`, keep it generic - a hotel-specific tweak belongs in
`tools/` or in your own adapter file, not in the shared runtime.
