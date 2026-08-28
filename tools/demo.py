#!/usr/bin/env python3
"""tools/demo.py - the whole loop on the bundled fixtures, zero credentials.

    make demo
    python3 tools/demo.py

Uses `load_settings(demo=True)`: mock provider, shadow mode, and the mock
adapter for every system, whatever `config/hotel.yaml` says. Runs against
its own database (`data/demo/demo.db`) so running it twice always shows the
same picture, and never touches `data/agent.db` (that is `make run`'s file).

It is also immune to a hotel's own connected data: `one_pass(..., demo=True)`
forces every `tools.ingest` read to `source="demo"`, which reads only from
the bundled `fixtures/inbound/` demo data dir and never even looks at
`data/imports/` - so once a hotel has written their own
`funnel_daily.csv`/`site_pages.csv` there (`workflows/00-setup.md` step 6),
`make demo` still shows exactly Hotel Aurora's numbers, never a mix of
theirs and the fixture's. See `tools/ingest.py`'s module docstring.

One thing this demo does that a real first run would not: it seeds ONE
experiment as already running, 14 days in, so you can see the whole loop
(propose -> start -> score -> decide) finish in a single pass instead of
waiting two weeks for real daily results - see docs/how-it-works.md "Design
decisions" #10. A real run always starts with zero running experiments.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings, sub_data_dir  # noqa: E402
from core.log import summary_line  # noqa: E402
from core.store import Store, StoreError  # noqa: E402
from tools.run import one_pass  # noqa: E402

DEMO_TODAY = "2026-09-15"

# Matches fixtures/inbound/funnel_experiment_daily.csv (page_slug=home,
# element=hero.cta.copy, 14 days of A/B results) and the first row of
# config/agent.example.yaml's experiment_catalog.
SEEDED_KEY = "2026-09-01:home:hero.cta.copy"
SEEDED_START = {
    "page_slug": "home", "element": "hero.cta.copy", "kind": "copy",
    "title": "Homepage hero button: a sharper call to action",
    "hypothesis": "\"Book Now\" describes an action, not a benefit.",
    "variant_a": "Book Now", "variant_b": "Check today's rate",
    "projected_eur": 400, "voice_note": None, "blocked_reason": None,
}


def _seed_running_experiment(store: Store) -> None:
    """Pretend a person started this test two weeks ago - see the module docstring."""
    item = store.upsert_item("funnel_engine", SEEDED_KEY, kind="experiment_start",
                             payload=SEEDED_START, unique_key=SEEDED_KEY)
    store.set_fields(item.id, draft=SEEDED_START)
    store.transition(item.id, "dispatched", "agent")
    store.transition(item.id, "pending_review", "agent")
    store.transition(item.id, "approved", "human", {"note": "demo seed"})
    store.transition(item.id, "sending", "agent", {"claim": True})
    store.transition(item.id, "sent", "agent", {"message_id": "demo-seed"})


def main() -> int:
    try:
        settings = load_settings(demo=True)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    demo_db = sub_data_dir("demo") / "demo.db"
    if demo_db.exists():
        demo_db.unlink()  # every `make demo` is a clean, repeatable run
    try:
        store = Store(settings, path=demo_db)
    except StoreError as exc:
        print(f"store error: {exc}", file=sys.stderr)
        return 1

    print("Funnel Hacking AI demo - Hotel Aurora, fixtures/inbound\n")
    _seed_running_experiment(store)

    code, stats = one_pass(settings, store, provider="mock", today=DEMO_TODAY, demo=True)
    if code != 0:
        print("demo: pass did not finish cleanly", file=sys.stderr)
        return 1

    counts = store.counts()
    waiting = sum(counts.get(s, 0) for s in ("pending_review", "needs_human"))
    print(f"\n{waiting} item(s) waiting for a person - starting a test and pushing a winner "
         "always do, see docs/safety.md.")
    print("Nothing was sent: mode is shadow, and demo never calls notify_staff() or "
         "sheets.append() on anything but the bundled fixtures.")
    print("Next: `make review` to see what is waiting, or read "
         "workflows/10-funnel-analysis.md.\n")

    demo_stats = {"processed": stats.get("processed", 0), "drafted": stats.get("processed", 0),
                 "sent": stats.get("auto_sent", 0)}
    print(f"DEMO OK — {summary_line(demo_stats, settings.mode)}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
