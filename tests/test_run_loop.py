"""Integration tests: the bundled fixtures, through tools/run.py's real
functions, with provider=mock and a throwaway store. No network, no
credentials - the same path `make demo` and a real overnight run both take.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings
from core.review import approve, reject
from core.store import Store
from tools.demo import DEMO_TODAY, _seed_running_experiment
from tools.funnel_engine import DailyRow, SitePage, aggregate_funnel, projected_monthly_eur
from tools.review import cmd_approve, cmd_send
from tools.run import _active_pairs, one_pass

TODAY = "2026-09-15"


def _settings_and_store(tmp_path, monkeypatch):
    """Isolated settings: a real `config/agent.yaml` (a hotel's own catalog,
    once they have written one) must never change what these tests exercise.
    `AGENT_CONFIG_DIR` points `load_settings()` at fresh copies of the
    shipped examples instead.
    """
    monkeypatch.chdir(REPO_ROOT)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "hotel.yaml").write_text(
        (REPO_ROOT / "config" / "hotel.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    (cfg_dir / "agent.yaml").write_text(
        (REPO_ROOT / "config" / "agent.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(cfg_dir))
    settings = load_settings(demo=True)
    store = Store(settings, path=tmp_path / "test.db")
    return settings, store


def test_one_pass_produces_proposals_on_the_fixtures(tmp_path, monkeypatch):
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    code, stats = one_pass(settings, store, provider="mock", today=TODAY)
    store.close()
    assert code == 0
    assert stats["processed"] > 0
    assert stats["pending_review"] > 0


def test_shadow_mode_never_marks_anything_sent(tmp_path, monkeypatch):
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    one_pass(settings, store, provider="mock", today=TODAY)
    counts = store.counts()
    store.close()
    assert counts.get("sent", 0) == 0
    assert counts.get("auto_sent", 0) == 0


def test_rerun_same_day_does_not_duplicate_proposals(tmp_path, monkeypatch):
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    one_pass(settings, store, provider="mock", today=TODAY)
    first_total = sum(store.counts().values())
    code, stats = one_pass(settings, store, provider="mock", today=TODAY)
    second_total = sum(store.counts().values())
    store.close()
    assert code == 0
    # every pair from the first pass is still pending_review, so _active_pairs()
    # drops every catalog entry before a proposal is even built - nothing to skip
    assert stats["processed"] == 0
    assert second_total == first_total


def test_dry_run_writes_nothing_to_the_store(tmp_path, monkeypatch):
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    settings.dry_run = True
    code, stats = one_pass(settings, store, provider="mock", today=TODAY)
    total = sum(store.counts().values())
    store.close()
    assert code == 0
    assert total == 0
    assert stats["processed"] > 0  # it still computed the analysis


def test_track_b_scores_a_seeded_running_experiment(tmp_path, monkeypatch):
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    _seed_running_experiment(store)
    code, stats = one_pass(settings, store, provider="mock", today=DEMO_TODAY)
    decisions = store.list_items(kind="experiment_decision")
    store.close()
    assert code == 0
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.review_status == "pending_review"  # a big swing always waits for a person
    assert decision.payload["click_lift"] > 0
    assert decision.payload["confidence"] >= 95.0


def test_concurrency_cap_blocks_starting_a_third_test(tmp_path, monkeypatch):
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    settings.mode = "live"
    settings.review.require_approval_for = []  # isolate the domain cap from the write guard
    one_pass(settings, store, provider="mock", today=TODAY)
    starts = store.list_items(kind="experiment_start", status="pending_review", limit=10)
    assert len(starts) >= 3  # the catalog ships four entries

    for item in starts[:2]:
        approve(store, item.id)
    cmd_send(store, settings, argparse.Namespace(limit=20))

    rc = cmd_approve(store, settings, argparse.Namespace(id=starts[2].id, note=""))
    store.close()
    assert rc == 1  # the third start is refused at the 2-test cap


def test_undecided_and_rejected_pairs_are_not_reproposed_next_day(tmp_path, monkeypatch):
    """Regression for FAIL Finding 3: a leak still sitting in the review
    queue - approved, still pending, or explicitly dismissed - must not get
    a brand-new duplicate `experiment_start` item the next time the daily
    cron runs, even though its unique_key is dated and therefore different
    from yesterday's.
    """
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    one_pass(settings, store, provider="mock", today=TODAY)
    starts = store.list_items(kind="experiment_start", status="pending_review", limit=10)
    assert len(starts) >= 3  # the catalog ships four entries

    approve(store, starts[0].id)                     # approved, not yet sent
    reject(store, starts[1].id, reason="not now")     # explicitly dismissed ("Dismiss")
    # starts[2:] are left at pending_review - still undecided either way

    before_ids = {i.id for i in store.list_items(kind="experiment_start", limit=50)}
    code, _stats = one_pass(settings, store, provider="mock", today="2026-09-16")
    after = store.list_items(kind="experiment_start", limit=50)
    store.close()

    assert code == 0
    after_ids = {i.id for i in after}
    assert after_ids == before_ids  # no new items at all - every pair was still undecided

    rejected_payload = starts[1].payload or {}
    same_pair = [i for i in after if (i.payload or {}).get("page_slug") == rejected_payload.get("page_slug")
                and (i.payload or {}).get("element") == rejected_payload.get("element")]
    assert len(same_pair) == 1
    assert same_pair[0].review_status == "rejected"  # the dismissed leak did not come back


def test_active_pairs_reopens_a_rejected_leak_once_its_numbers_move(tmp_path, monkeypatch):
    """A `rejected` pair stays quiet while the underlying leak is unchanged,
    but is offered again once its projected EUR value has moved by at least
    `rejected_reopen_pct` - a rejection is "not this leak, as priced", not
    "never mention this page/element again."
    """
    settings, store = _settings_and_store(tmp_path, monkeypatch)
    cfg = settings.agent
    page = SitePage(slug="home", title="Home", path="/", kind="page",
                    sessions_30d=1000, engine_clicks_30d=20)  # 2% - below the 4% floor
    pages_by_slug = {"home": page}
    daily = [DailyRow(date="2026-09-01", source="direct", sessions=1000, engine_clicks=20,
                      bookings=10, revenue=2000.0)]
    agg = aggregate_funnel(daily, cfg.get("window_days", 30))
    current = projected_monthly_eur(page, agg, cfg)
    assert current > 0  # the fixture must actually price a leak, or this test proves nothing

    def _rejected_start(element: str, projected_eur: float):
        payload = {"page_slug": "home", "element": element, "kind": "copy", "title": "t",
                  "hypothesis": "h", "variant_a": "a", "variant_b": "b",
                  "projected_eur": projected_eur, "voice_note": None, "blocked_reason": None}
        item, _created = store.upsert_unique("experiment_start", f"2026-09-01:home:{element}",
                                             payload, source="funnel_engine")
        store.transition(item.id, "dispatched", "agent")
        store.transition(item.id, "pending_review", "agent")
        return reject(store, item.id, reason="not now")

    _rejected_start("hero.cta.copy", projected_eur=current)         # unchanged since rejection
    _rejected_start("hero.cta.subline", projected_eur=current * 0.5)  # moved 50% - well past 20%

    pairs = _active_pairs(store, daily, pages_by_slug, cfg)
    store.close()
    assert ("home", "hero.cta.copy") in pairs        # numbers unchanged - stays quiet
    assert ("home", "hero.cta.subline") not in pairs  # materially different - eligible again
