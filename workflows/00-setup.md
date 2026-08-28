# Workflow: first-run setup

Objective: get Funnel Hacking AI from a fresh clone to a working demo, then
to a real catalog of your own test ideas, in one sitting.

## Steps

1. **Install and check.**
   ```bash
   make setup
   make doctor
   ```
   `make setup` creates the virtualenv, installs `requirements.txt`, and
   copies `.env.example` -> `.env` and every `config/*.example.yaml` ->
   `config/*.yaml` (only if those files do not exist yet - it never
   overwrites your own copies). `make doctor` will show a `FAIL` on "hotel
   identity" right after setup - that is expected, it means the property
   name is still the shipped placeholder. Everything else should be `ok` or
   `warn`.

2. **Run the demo.** No credentials needed.
   ```bash
   make demo
   ```
   Expect to see 4 items processed (3 fresh proposals plus one scored,
   already-running experiment) and the line
   `DEMO OK — 4 items processed, 4 drafted, 0 sent (shadow)`. If you do not
   see that, stop and read `workflows/99-troubleshooting.md` before going
   further.

3. **Fill in the property.** Edit `config/hotel.yaml` (name, address,
   currency, contact). This agent does not read `knowledge/property.md` or
   `knowledge/faq.md` in any prompt - see `knowledge/README.md` - so you can
   skip those. Copy `knowledge/brand-voice.example.md` to
   `knowledge/brand-voice.md` and write a short version of your property's
   tone of voice; it is what `brand_voice_note` in `config/agent.yaml` should
   point a person back to.

4. **Write your experiment catalog, and check the numbers behind it.** This
   is the one step that actually makes the agent useful - the engine never
   invents copy (see `docs/how-it-works.md` "Design decisions" #2). Open
   `config/agent.yaml` and, for `experiment_catalog:`, either keep the four
   shipped examples (a reasonable starting set for most hotel sites) or
   replace them with your own: one page, one variable, per row. Every
   `page_slug` must match a row you will export in `site_pages` - see step
   6.

   While you are in `config/agent.yaml`, also look at `economics:` and
   `benchmarks:` above the catalog - do not skip this, even to come back to
   it later. `economics.avg_booking_value` (ships at 260, Hotel Aurora's
   placeholder, in `hotel.currency`) feeds **every euro figure this agent
   ever prints**, and `benchmarks:` sets the click/search/booking bands
   every page is judged against. Wrong numbers here do not cause an error -
   the agent will confidently price leaks and proposals against a stranger's
   property all the way to `workflows/90-go-live.md`'s checklist, which is
   the last, not the first, place that asks you to trust them. Put in your
   own average booking value now (ask whoever owns your PMS/booking-engine
   reporting if you are not sure) and re-source the benchmark bands if this
   property is a restaurant, not a hotel - see `docs/how-it-works.md`
   "Restaurant lens".

5. **Pick how the agent thinks.** `config/hotel.yaml`'s `llm.provider`
   starts as `interactive` - it asks you, in this Claude Code session,
   instead of calling a model. That costs nothing extra and is the best way
   to see the growth note it writes. `docs/how-it-works.md` and
   `docs/safety.md` explain the other three providers (`mock`,
   `claude-code`, `anthropic`) and when to move to one of them. The model
   never decides a bottleneck, a winner, or a piece of copy - only the note.

6. **Connect your real data (optional for now).** `docs/integrations.md`
   lists every CSV this agent reads and its exact columns:
   `funnel_daily.csv` (your analytics + booking-engine export),
   `site_pages.csv` (your page catalog), `funnel_experiment_daily.csv` (your
   A/B testing tool's daily export), plus `seo_keywords.csv` and the two
   OTA-content files. Drop your own exports into `data/imports/` - each one
   falls back to the bundled fixture in `fixtures/inbound/` until you do.

7. **Connect messaging and a sheet (optional for now).** `systems.messaging`
   and `systems.sheets` in `config/hotel.yaml` start as `mock` /
   `csv`-to-`data/exports/`. `docs/integrations.md` covers `unipile` and
   `webhook` for messaging, and Google Sheets for a live shared sheet. Run
   `make doctor` after changing either.

8. **Re-check.**
   ```bash
   make doctor
   ```
   Once the property name is real, the "hotel identity" line turns green.
   Move on to `workflows/10-funnel-analysis.md` to run the loop for real.
