"""Unit tests for tools/funnel_engine.py - pure functions, no I/O, no store."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.funnel_engine import (CatalogEntry, DailyRow, ExperimentArm, SitePage, aggregate_funnel,
                                 build_proposals, can_publish, classify_decision, experiment_stats,
                                 judge_stages, money, projected_monthly_eur, rank_bottleneck)

CFG = {
    "benchmarks": {"click_low_pct": 4.0, "click_high_pct": 6.0, "content_click_low_pct": 1.0,
                   "search_healthy_floor_pct": 50.0, "search_book_low_pct": 25.0,
                   "search_book_high_pct": 35.0},
    "economics": {"avg_booking_value": 260, "marginal_factor": 0.5, "round_projected_to": 100,
                 "round_measured_to": 50},
    "significance_bar_pct": 95.0, "min_days_running": 14, "max_concurrent_experiments": 2,
    "big_swing_pct": 25.0,
    "rules": {"seo_watch": True, "brand_voice_lock": True, "max_2_concurrent": True,
             "significance_95": True, "auto_rollout": False},
    "brand_voice_note": "Check the tone before you ship it.",
}


def _daily_rows() -> list[DailyRow]:
    """10 days, one source, a steady 3% click-through - under the 4% benchmark."""
    return [DailyRow(date=f"2026-09-{i+1:02d}", source="direct", reach=1000, sessions=100,
                     engine_clicks=3, engine_searches=2, bookings=1, revenue=260)
           for i in range(10)]


def test_aggregate_funnel_sums_the_window():
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    assert agg.days == 10
    assert agg.sessions == 1000
    assert agg.engine_clicks == 30
    assert agg.click_rate == 3.0


def test_aggregate_funnel_keeps_only_the_most_recent_window():
    rows = _daily_rows() + [DailyRow(date="2020-01-01", source="direct", sessions=99999)]
    agg = aggregate_funnel(rows, window_days=10)
    assert agg.days == 10
    assert agg.sessions == 1000  # the stale 2020 row is outside the 10-day window


def test_judge_stages_computes_real_verdicts_from_the_real_numbers():
    rows = [DailyRow(date="2026-09-01", source="direct", sessions=1000, engine_clicks=35,
                     engine_searches=10, bookings=3, revenue=780)]
    agg = aggregate_funnel(rows, window_days=30)
    verdicts = judge_stages(agg, CFG)
    assert verdicts["click"] == "well under the benchmark"       # 3.5% < 4.0%
    assert verdicts["search"] == "below what is typical for this stage"  # 28.57% < 50% floor
    assert verdicts["book"] == "healthy"                         # 30.0%, inside 25-35%


def test_projected_monthly_eur_is_zero_once_a_page_clears_its_benchmark():
    healthy_page = SitePage(slug="rooms", title="Rooms", path="/rooms", kind="page",
                            sessions_30d=1000, engine_clicks_30d=60)  # 6.0% - at the benchmark
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    assert projected_monthly_eur(healthy_page, agg, CFG) == 0.0


def test_projected_monthly_eur_prices_a_real_leak():
    leaking_page = SitePage(slug="home", title="Home", path="/", kind="page",
                            sessions_30d=2000, engine_clicks_30d=40)  # 2.0%, well under 4%
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    assert projected_monthly_eur(leaking_page, agg, CFG) > 0


def test_rank_bottleneck_picks_the_largest_recoverable_page():
    small_leak = SitePage(slug="offers", title="Offers", path="/offers", sessions_30d=200,
                          engine_clicks_30d=6)
    big_leak = SitePage(slug="home", title="Home", path="/", sessions_30d=3000,
                        engine_clicks_30d=60)
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    bottleneck = rank_bottleneck([small_leak, big_leak], agg, CFG)
    assert bottleneck is not None
    assert bottleneck.page_slug == "home"


def test_rank_bottleneck_is_none_when_nothing_leaks():
    fine_page = SitePage(slug="rooms", title="Rooms", path="/rooms", sessions_30d=1000,
                         engine_clicks_30d=60)
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    assert rank_bottleneck([fine_page], agg, CFG) is None


def _catalog() -> list[CatalogEntry]:
    return [
        CatalogEntry(page_slug="home", element="hero.cta.copy", kind="copy",
                    title="Sharper CTA", hypothesis="...", variant_a="Book Now",
                    variant_b="Check today's rate"),
        CatalogEntry(page_slug="journal-a", element="article.cta", kind="copy",
                    title="In-article booking prompt", hypothesis="...",
                    variant_a="(none)", variant_b="Check availability"),
    ]


def _pages() -> dict[str, SitePage]:
    return {
        "home": SitePage(slug="home", title="Home", path="/", kind="page", sessions_30d=2000,
                         engine_clicks_30d=40),
        "journal-a": SitePage(slug="journal-a", title="Journal", path="/journal/a", kind="blog",
                              sessions_30d=900, engine_clicks_30d=5),
    }


def test_build_proposals_suppresses_blog_pages_when_seo_watch_is_off():
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    cfg = {**CFG, "rules": {**CFG["rules"], "seo_watch": False}}
    proposals, suppressed = build_proposals(_catalog(), _pages(), agg, set(), 0, cfg)
    slugs = {p.page_slug for p in proposals}
    assert "journal-a" not in slugs
    assert any(s.page_slug == "journal-a" for s in suppressed)


def test_build_proposals_never_reproposes_an_active_pair():
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    active = {("home", "hero.cta.copy")}
    proposals, _ = build_proposals(_catalog(), _pages(), agg, active, 1, CFG)
    assert all(p.page_slug != "home" for p in proposals)


def test_build_proposals_attaches_a_voice_note_to_copy_entries():
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    proposals, _ = build_proposals(_catalog(), _pages(), agg, set(), 0, CFG)
    home_proposal = next(p for p in proposals if p.page_slug == "home")
    assert home_proposal.voice_note == CFG["brand_voice_note"]


def test_build_proposals_flags_blocked_at_the_concurrency_cap():
    agg = aggregate_funnel(_daily_rows(), window_days=30)
    proposals, _ = build_proposals(_catalog(), _pages(), agg, set(), 2, CFG)  # cap is 2
    assert all(p.blocked_reason for p in proposals)


def test_experiment_stats_finds_a_significant_positive_lift():
    a = ExperimentArm("a", sessions=700, clicks=14, bookings=3)
    b = ExperimentArm("b", sessions=686, clicks=27, bookings=6)
    stats = experiment_stats(a, b, days=14)
    assert stats.click_lift > 0
    assert stats.significant is True
    assert stats.confidence >= 95.0


def test_can_publish_rejects_a_negative_lift_even_if_significant():
    a = ExperimentArm("a", sessions=700, clicks=27, bookings=3)   # a now wins
    b = ExperimentArm("b", sessions=686, clicks=14, bookings=6)
    stats = experiment_stats(a, b, days=14)
    ok, reason = can_publish(stats, CFG)
    assert ok is False
    assert "not beating control" in reason


def test_classify_decision_holds_a_big_swing_for_a_human_even_with_auto_rollout_on():
    a = ExperimentArm("a", sessions=700, clicks=14, bookings=3)
    b = ExperimentArm("b", sessions=686, clicks=27, bookings=6)   # ~+97% click lift
    stats = experiment_stats(a, b, days=14)
    cfg = {**CFG, "rules": {**CFG["rules"], "auto_rollout": True}}
    auto, reason = classify_decision(stats, cfg)
    assert auto is False
    assert "big swing" in reason


def test_classify_decision_auto_publishes_a_modest_significant_win_when_rollout_is_on():
    a = ExperimentArm("a", sessions=20000, clicks=800, bookings=160)
    b = ExperimentArm("b", sessions=20000, clicks=920, bookings=176)  # +15% click lift
    stats = experiment_stats(a, b, days=14)
    cfg = {**CFG, "rules": {**CFG["rules"], "auto_rollout": True}}
    auto, reason = classify_decision(stats, cfg)
    assert auto is True
    assert reason is None


def test_money_uses_the_given_currency_never_a_hardcoded_symbol():
    assert money(1234, "GBP") == "GBP 1,234"
    assert money(-50, "NOK") == "-NOK 50"
