#!/usr/bin/env python3
"""tools/run.py - Funnel Hacking AI's main loop: ingest -> analyze -> propose ->
score running experiments -> queue -> narrate.

    python3 tools/run.py --once
    python3 tools/run.py --watch
    python3 tools/run.py --once --dry-run
    python3 tools/run.py --once --provider mock

Every pass does two things, in order: Track A proposes new experiments from
`config/agent.yaml`'s catalog (docs/how-it-works.md "The main loop"), and
Track B scores every currently running experiment that has enough daily
data (docs/how-it-works.md "The experiment loop"). Starting a test and
pushing a winner both always wait for a human to run `tools/review.py
approve` + `send`, unless `rules.auto_rollout` is on - and even then,
`core.review`'s guard still has the final word.

Exit codes: 0 ok, 3 waiting on an `interactive` narrative answer, 1 a real error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging, get_sheets  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.llm import LLMError, LLMPendingInteractive, complete  # noqa: E402
from core.log import Run, get_logger, summary_line  # noqa: E402
from core.review import WriteBlocked  # noqa: E402
from core.store import Item, Store, StoreError  # noqa: E402
from core.templates import build_prompt  # noqa: E402
from tools import ingest  # noqa: E402
from tools.funnel_engine import (ExperimentStats, aggregate_funnel, catalog_from_cfg,
                                 classify_decision, experiment_stats, measured_monthly_eur,
                                 money, projected_monthly_eur, run_funnel_analysis)  # noqa: E402

log = get_logger("run")

#: A "Dismiss" on an experiment_start stays quiet - see docs/how-it-works.md
#: "Step 5" - until the page's projected monthly EUR value has moved by at
#: least this many percent since the rejection. Override with
#: `config/agent.yaml: rejected_reopen_pct`.
REJECTED_REOPEN_PCT = 20.0


def _get_by_unique(store: Store, kind: str, unique_key: str) -> Item | None:
    """Look up one item by (kind, unique_key) without creating it - see core/store.py."""
    row = store.db.execute("SELECT * FROM items WHERE kind=? AND unique_key=?",
                           (kind, unique_key)).fetchone()
    return Item.from_row(row) if row else None


# --------------------------------------------------------------------------
# Track A: propose
# --------------------------------------------------------------------------
def _running_pairs(store: Store) -> set[tuple[str, str]]:
    """(page_slug, element) pairs whose test has actually started (`sent` /
    `auto_sent`) and is not yet decided - i.e. genuinely consuming one of
    the `max_concurrent_experiments` concurrency-cap slots right now.

    This is deliberately narrower than `_active_pairs()` below: a proposal
    merely sitting at `pending_review` has not started anything yet, so it
    must not count against the cap (or a hotel could never approve past the
    first `max_concurrent_experiments` proposals in the queue). Used only
    by `tools/review.py cmd_approve`'s cap check - see
    docs/how-it-works.md "Design decisions" #7.
    """
    pairs: set[tuple[str, str]] = set()
    for item in store.list_items(kind="experiment_start", status=["sent", "auto_sent"], limit=500):
        p = item.payload or {}
        key = (p.get("page_slug", ""), p.get("element", ""))
        decision = _get_by_unique(store, "experiment_decision", f"decision:{item.id}")
        if decision is None or decision.review_status not in ("sent", "auto_sent", "rejected"):
            pairs.add(key)
    return pairs


def _active_pairs(store: Store, daily, pages_by_slug: dict, cfg: dict) -> set[tuple[str, str]]:
    """(page_slug, element) pairs that must not get a new proposal today.

    `build_proposals()` silently drops any catalog entry whose pair is in
    this set - see docs/how-it-works.md "Step 5" ("not already the subject
    of a running or undecided test"). Every `experiment_start` item ever
    queued for a pair is considered; the most recently updated one decides:

    - `pending_review` / `needs_human` / `approved` / `edited`: a human has
      not finished with this proposal yet.
    - `sent` / `auto_sent`: the test is actually running - stays active
      until its `experiment_decision` reaches a terminal status.
    - `rejected` ("Dismiss"): stays quiet - a human already said no to
      exactly this pair - UNLESS the page's projected monthly EUR value has
      moved by at least `rejected_reopen_pct` (default
      `REJECTED_REOPEN_PCT` = 20%) since the rejection. That threshold is
      the line between "the same leak, still dismissed" and "materially a
      different leak, worth asking about again." A pair with no prior
      projection on file (e.g. an old fixture) is treated as changed, so it
      is never stuck quiet forever on a missing number.

    Anything else (a fresh `new`/`dispatched` row, mid-send `sending`, a
    `failed` send awaiting retry, or `stale`) is treated the same as
    undecided: still active, not re-proposed.
    """
    reopen_pct = cfg.get("rejected_reopen_pct", REJECTED_REOPEN_PCT)
    agg = None  # computed lazily - only rejected pairs need it

    latest_by_pair: dict[tuple[str, str], Item] = {}
    for item in store.list_items(kind="experiment_start", limit=1000):
        p = item.payload or {}
        key = (p.get("page_slug", ""), p.get("element", ""))
        if key == ("", ""):
            continue
        prev = latest_by_pair.get(key)
        if prev is None or (item.updated_at or "") >= (prev.updated_at or ""):
            latest_by_pair[key] = item

    pairs: set[tuple[str, str]] = set()
    for key, item in latest_by_pair.items():
        status = item.review_status
        if status in ("sent", "auto_sent"):
            decision = _get_by_unique(store, "experiment_decision", f"decision:{item.id}")
            if decision is None or decision.review_status not in ("sent", "auto_sent", "rejected"):
                pairs.add(key)
            continue
        if status == "rejected":
            page = pages_by_slug.get(key[0])
            previous = (item.payload or {}).get("projected_eur") or 0.0
            if page is not None and previous:
                if agg is None:
                    agg = aggregate_funnel(daily, cfg.get("window_days", 30))
                current = projected_monthly_eur(page, agg, cfg)
                moved_pct = abs(current - previous) / previous * 100
                if moved_pct >= reopen_pct:
                    continue  # the leak changed enough to be worth a fresh look
            pairs.add(key)
            continue
        if status == "skipped":
            continue  # explicitly thrown away, never used for this item kind - free to repropose
        # pending_review / needs_human / approved / edited, and anything
        # transient (new / dispatched / sending / failed / stale): undecided.
        pairs.add(key)
    return pairs


def _proposal_dict(p) -> dict:
    return {"page_slug": p.page_slug, "element": p.element, "kind": p.kind, "title": p.title,
           "hypothesis": p.hypothesis, "variant_a": p.variant_a, "variant_b": p.variant_b,
           "projected_eur": p.projected_eur, "voice_note": p.voice_note,
           "blocked_reason": p.blocked_reason}


def _queue_proposals(store: Store, proposals, today: str, stats: dict) -> None:
    for p in proposals:
        payload = _proposal_dict(p)
        item, created = store.upsert_unique("experiment_start", p.unique_key(today), payload,
                                            source="funnel_engine")
        if not created:
            stats["skipped"] += 1
            continue
        stats["processed"] += 1
        store.set_fields(item.id, draft=payload)
        store.transition(item.id, "dispatched", "agent")
        # Starting a test is always a human "Apply change" decision - see
        # docs/how-it-works.md "Step 6". There is no auto path here at all.
        store.transition(item.id, "pending_review", "agent",
                         {"blocked_reason": p.blocked_reason} if p.blocked_reason else None)
        stats["pending_review"] += 1


def _publish_start(messaging, item: Item) -> str | None:
    d = item.payload or {}
    text = (f"Start test: {d.get('title')}\n"
           f"Page: {d.get('page_slug')}  Element: {d.get('element')}\n"
           f"A (control): {d.get('variant_a')}\n"
           f"B (variant): {d.get('variant_b')}\n"
           f"Split 50/50 in your CMS or A/B testing tool. Log daily results to "
           f"data/imports/funnel_experiment_daily.csv so this agent can score it.")
    result = messaging.notify_staff(text, item=item)
    return result.get("message_id") if isinstance(result, dict) else None


# --------------------------------------------------------------------------
# Track B: score a running experiment, then gate the push
# --------------------------------------------------------------------------
def _decision_dict(page_slug: str, element: str, title: str, stats: ExperimentStats, page,
                   cfg: dict, currency: str) -> dict:
    measured = measured_monthly_eur(stats, page, cfg) if page else None
    return {
        "page_slug": page_slug, "element": element, "title": title, "days": stats.days,
        "a_click_rate": stats.a.click_rate, "b_click_rate": stats.b.click_rate,
        "a_sessions": stats.a.sessions, "b_sessions": stats.b.sessions,
        "click_lift": stats.click_lift, "booking_lift": stats.booking_lift,
        "confidence": stats.confidence, "significant": stats.significant, "z": stats.z,
        "measured_eur": measured, "measured_text": money(measured, currency) if measured else None,
    }


def _publish_decision(messaging, sheets, item: Item) -> str | None:
    d = item.payload or {}
    text = (f"Push winner: {d.get('title')}\n"
           f"Page: {d.get('page_slug')}  Element: {d.get('element')}\n"
           f"Click-through {d.get('a_click_rate')}% -> {d.get('b_click_rate')}% "
           f"({d.get('click_lift'):+.1f}%), confidence {d.get('confidence')}% over "
           f"{d.get('days')} days.\n"
           f"Measured impact: about {d.get('measured_text') or 'not enough booking data yet'}/mo.\n"
           f"Implement variant B as the new control in your CMS or testing tool.")
    result = messaging.notify_staff(text, item=item)
    sheets.append("experiment_decisions",
                  [[d.get("page_slug"), d.get("element"), d.get("title"), d.get("click_lift"),
                    d.get("confidence"), d.get("measured_eur"), "rolled out"]], item=item)
    return result.get("message_id") if isinstance(result, dict) else None


def _queue_decisions(store: Store, messaging, sheets, active_pairs: set[tuple[str, str]],
                     pages_by_slug: dict, cfg: dict, currency: str, stats: dict,
                     source: str | None = None) -> None:
    daily = ingest.load_experiment_daily(source=source)
    min_days = cfg.get("min_days_running", 14)
    starts_by_key: dict[tuple[str, str], Item] = {}
    for item in store.list_items(kind="experiment_start", status=["sent", "auto_sent"], limit=500):
        p = item.payload or {}
        starts_by_key[(p.get("page_slug", ""), p.get("element", ""))] = item

    for key in active_pairs:
        start_item = starts_by_key.get(key)
        if start_item is None:
            continue
        if _get_by_unique(store, "experiment_decision", f"decision:{start_item.id}") is not None:
            continue  # already scored this round
        bucket = daily.get(key)
        if bucket is None or bucket["days"] < min_days:
            continue  # not enough data yet - retry next pass
        page_slug, element = key
        page = pages_by_slug.get(page_slug)
        exp_stats = experiment_stats(bucket["a"], bucket["b"], bucket["days"],
                                     cfg.get("significance_bar_pct", 95.0))
        title = (start_item.payload or {}).get("title", f"{page_slug} {element}")
        payload = _decision_dict(page_slug, element, title, exp_stats, page, cfg, currency)
        item, created = store.upsert_unique("experiment_decision", f"decision:{start_item.id}",
                                            payload, source="funnel_engine")
        if not created:
            stats["skipped"] += 1
            continue
        stats["processed"] += 1
        store.set_fields(item.id, draft=payload)
        store.transition(item.id, "dispatched", "agent")
        auto, hold_reason = classify_decision(exp_stats, cfg)
        if auto:
            try:
                message_id = _publish_decision(messaging, sheets, item)
                if message_id:
                    store.set_fields(item.id, sent_message_id=message_id)
                store.transition(item.id, "auto_sent", "agent", {"published": True})
                stats["auto_sent"] += 1
                continue
            except WriteBlocked as exc:
                store.transition(item.id, "pending_review", "agent", {"blocked": str(exc)[:200]})
                stats["pending_review"] += 1
                continue
            except Exception as exc:  # noqa: BLE001 - record and move on, never crash the run
                store.set_fields(item.id, error=str(exc)[:500])
                store.transition(item.id, "failed", "agent", {"error": str(exc)[:300]})
                stats["needs_human"] += 1
                continue
        store.transition(item.id, "pending_review", "agent", {"hold_reason": hold_reason})
        stats["pending_review"] += 1


# --------------------------------------------------------------------------
# narration + the pass
# --------------------------------------------------------------------------
def _narrate(settings, store, provider: str | None, result, currency: str) -> str | None:
    """Best-effort: a narration failure never fails a run that already succeeded."""
    schema = json.loads((REPO_ROOT / "prompts" / "schemas" / "funnel_note.json")
                        .read_text(encoding="utf-8"))
    proposals = [{"title": p.title,
                 "worth": (money(p.projected_eur, currency) + " a month") if p.projected_eur else None}
                for p in result.proposals[:8]]
    item = {"summary": result.summary, "proposals": proposals,
           "suppressed": [{"title": s.title, "reason": s.reason} for s in result.suppressed]}
    prompt = build_prompt("funnel_note", settings=settings, item=item, fixture_id="funnel-note-01")
    try:
        res = complete("funnel_note", prompt, schema, settings=settings, provider=provider,
                       store=None if settings.dry_run else store)
        return (res.data or {}).get("note")
    except LLMPendingInteractive:
        raise
    except LLMError as exc:
        log.warn("funnel_note skipped", error=str(exc)[:200])
        return None


def one_pass(settings, store: Store, *, provider: str | None = None, today: str | None = None,
            demo: bool = False) -> tuple[int, dict]:
    """Run one full pass. ``demo=True`` (only `tools/demo.py`) forces every
    `tools.ingest` read to `source="demo"` - fixtures/inbound only, never
    `data/imports/` - so `make demo`'s output can never be changed by, or
    leak, a hotel's own connected data. See `tools/ingest.py`'s module
    docstring and docs/how-it-works.md "Design decisions".
    """
    stats = {"processed": 0, "skipped": 0, "pending_review": 0, "auto_sent": 0,
            "needs_human": 0, "sent": 0}
    cfg = settings.agent
    currency = settings.hotel.currency
    today = today or date.today().isoformat()
    source = ingest.DEMO_SOURCE if demo else None

    with Run("funnel_analysis", settings, None if settings.dry_run else store) as run:
        daily = ingest.load_funnel_daily(source=source)
        pages = ingest.load_site_pages(source=source)
        pages_by_slug = {p.slug: p for p in pages}
        catalog = catalog_from_cfg(cfg)

        active_pairs = _active_pairs(store, daily, pages_by_slug, cfg)  # a read - safe under --dry-run
        result = run_funnel_analysis(daily, pages, catalog, active_pairs, len(active_pairs),
                                     cfg, currency)

        if settings.dry_run:
            stats["processed"] = len(result.proposals)
        else:
            _queue_proposals(store, result.proposals, today, stats)
            messaging = get_messaging(settings)
            sheets = get_sheets(settings)
            _queue_decisions(store, messaging, sheets, active_pairs, pages_by_slug, cfg,
                             currency, stats, source=source)
            reaped = store.reap_stuck_sending()
            stale = store.mark_stale(72)
            if reaped:
                log.warn("reaped stuck sends", count=len(reaped))
            if stale:
                log.info("marked stale", count=len(stale))

        stats["drafted"] = stats["processed"]
        run.stats = {**stats, "summary": result.summary}

        try:
            note = _narrate(settings, store, provider, result, currency)
            if note:
                print(f"\nGrowth note: {note}\n")
        except LLMPendingInteractive as exc:
            print(str(exc))
            return 3, stats

    for line in result.thinking_log:
        print(f"  - {line}")
    return 0, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--once", action="store_true", help="run a single pass (default)")
    mode_group.add_argument("--watch", action="store_true",
                            help="keep running on the configured interval")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute everything, write nothing, even in live mode")
    parser.add_argument("--provider", default=None, help="override llm.provider for this run")
    parser.add_argument("--as-of", default=None,
                        help="override today's date (YYYY-MM-DD) - mainly for tests/demo")
    parser.add_argument("--poll-seconds", type=int, default=None,
                        help="override the --watch interval (default: agent.yaml or 6h)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(provider=args.provider, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    try:
        store = Store(settings)
    except StoreError as exc:
        print(f"store error: {exc}", file=sys.stderr)
        return 1
    try:
        def pass_fn():
            return one_pass(settings, store, provider=args.provider, today=args.as_of)

        if args.watch:
            poll_seconds = args.poll_seconds or int(settings.agent_get("poll_seconds", 21600))
            while True:
                code, stats = pass_fn()
                print(summary_line({"processed": stats.get("processed", 0),
                                    "drafted": stats.get("processed", 0),
                                    "sent": stats.get("auto_sent", 0)}, settings.mode))
                if code != 0:
                    return code
                time.sleep(poll_seconds)
        code, stats = pass_fn()
        print(summary_line({"processed": stats.get("processed", 0),
                            "drafted": stats.get("processed", 0),
                            "sent": stats.get("auto_sent", 0)}, settings.mode))
        return code
    except (LLMError, AdapterError, StoreError, WriteBlocked) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
