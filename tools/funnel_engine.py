"""tools/funnel_engine.py - Funnel Hacking AI's whole decision engine. Pure functions.

No I/O anywhere in this file: every function takes plain dataclasses in and
returns plain dataclasses out. `tools/run.py` is the only place that talks to
the store or an LLM. This split is what lets `tools/demo.py` and every test
in `tests/test_funnel_engine.py` exercise the exact same code path a real
overnight run does.

This engine never proposes a rate change and never writes to a live page -
see docs/how-it-works.md and docs/safety.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SOURCE_ORDER = ("meta_ads", "google_ads", "organic", "direct", "email", "ota_referral")


def money(amount: float, currency: str = "EUR") -> str:
    """Every human- or model-facing amount goes through this. Never hardcode a symbol."""
    sign = "-" if amount < 0 else ""
    return f"{sign}{currency} {abs(amount):,.0f}"


def pct(numerator: float, denominator: float) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


# --------------------------------------------------------------------------
# plain data
# --------------------------------------------------------------------------
@dataclass
class DailyRow:
    """One (date, source) cell of the funnel export."""

    date: str
    source: str
    reach: int = 0
    sessions: int = 0
    engine_clicks: int = 0
    engine_searches: int = 0
    bookings: int = 0
    revenue: float = 0.0


@dataclass
class SourceAgg:
    source: str
    reach: int = 0
    sessions: int = 0
    engine_clicks: int = 0
    engine_searches: int = 0
    bookings: int = 0
    revenue: float = 0.0

    @property
    def click_rate(self) -> float:
        return pct(self.engine_clicks, self.sessions)


@dataclass
class FunnelAgg:
    """The whole funnel, summed over the analysis window, plus a per-source split."""

    days: int
    reach: int = 0
    sessions: int = 0
    engine_clicks: int = 0
    engine_searches: int = 0
    bookings: int = 0
    revenue: float = 0.0
    by_source: dict[str, SourceAgg] = field(default_factory=dict)

    @property
    def click_rate(self) -> float:
        return pct(self.engine_clicks, self.sessions)

    @property
    def search_rate(self) -> float:
        return pct(self.engine_searches, self.engine_clicks)

    @property
    def book_rate(self) -> float:
        return pct(self.bookings, self.engine_searches)

    @property
    def session_to_book(self) -> float:
        return pct(self.bookings, self.sessions)

    @property
    def bookings_per_click(self) -> float:
        return (self.bookings / self.engine_clicks) if self.engine_clicks else 0.0


@dataclass
class SitePage:
    """One page from `site_pages` - the read model this agent prices a leak against."""

    slug: str
    title: str
    path: str
    kind: str = "page"          # page | blog
    sessions_30d: int = 0
    engine_clicks_30d: int = 0
    sort: int = 0

    @property
    def click_rate(self) -> float:
        return pct(self.engine_clicks_30d, self.sessions_30d)


@dataclass
class CatalogEntry:
    """One hand-authored test idea from config/agent.yaml: experiment_catalog."""

    page_slug: str
    element: str
    kind: str            # copy | image | placement | layout - gates brand_voice_lock
    title: str
    hypothesis: str
    variant_a: str
    variant_b: str


@dataclass
class Proposal:
    """One catalog entry the engine is willing to surface this run."""

    page_slug: str
    element: str
    kind: str
    title: str
    hypothesis: str
    variant_a: str
    variant_b: str
    projected_eur: float | None
    voice_note: str | None = None
    blocked_reason: str | None = None

    def unique_key(self, today: str) -> str:
        return f"{today}:{self.page_slug}:{self.element}"


@dataclass
class Suppressed:
    """A catalog entry that never became a proposal this run, and why."""

    page_slug: str
    element: str
    title: str
    reason: str


@dataclass
class Bottleneck:
    stage: str
    page_slug: str
    rate: float
    benchmark_low: float
    benchmark_high: float
    projected_eur: float


@dataclass
class AnalysisResult:
    thinking_log: list[str]
    agg: FunnelAgg
    bottleneck: Bottleneck | None
    proposals: list[Proposal]
    suppressed: list[Suppressed]
    healthy: list[dict]
    summary: dict


# --------------------------------------------------------------------------
# Track A: the daily analysis
# --------------------------------------------------------------------------
def aggregate_funnel(rows: list[DailyRow], window_days: int = 30) -> FunnelAgg:
    """Sum the most recent `window_days` distinct dates in `rows`, in total and per source.

    A fixture with fewer distinct dates than the window is summed in full,
    never padded with zeros.
    """
    dates = sorted({r.date for r in rows})
    window = set(dates[-window_days:]) if window_days else set(dates)
    agg = FunnelAgg(days=len(window))
    by_source: dict[str, SourceAgg] = {}
    for row in rows:
        if row.date not in window:
            continue
        agg.reach += row.reach
        agg.sessions += row.sessions
        agg.engine_clicks += row.engine_clicks
        agg.engine_searches += row.engine_searches
        agg.bookings += row.bookings
        agg.revenue += row.revenue
        s = by_source.setdefault(row.source, SourceAgg(source=row.source))
        s.reach += row.reach
        s.sessions += row.sessions
        s.engine_clicks += row.engine_clicks
        s.engine_searches += row.engine_searches
        s.bookings += row.bookings
        s.revenue += row.revenue
    agg.by_source = by_source
    return agg


def _band_verdict(rate: float, low: float, high: float) -> str:
    if rate < low:
        return "well under the benchmark"
    if rate > high:
        return "above the benchmark"
    if rate >= high * 0.9:
        return "at the top of the band"
    return "healthy"


def _floor_verdict(rate: float, floor: float) -> str:
    return "healthy" if rate >= floor else "below what is typical for this stage"


def judge_stages(agg: FunnelAgg, cfg: dict) -> dict[str, str]:
    """Real verdicts computed from the real numbers - see docs/how-it-works.md #4."""
    b = cfg.get("benchmarks", {})
    return {
        "click": _band_verdict(agg.click_rate, b.get("click_low_pct", 4.0),
                               b.get("click_high_pct", 6.0)),
        "search": _floor_verdict(agg.search_rate, b.get("search_healthy_floor_pct", 50.0)),
        "book": _band_verdict(agg.book_rate, b.get("search_book_low_pct", 25.0),
                              b.get("search_book_high_pct", 35.0)),
    }


def page_benchmark_low(page: SitePage, cfg: dict) -> float:
    b = cfg.get("benchmarks", {})
    return b.get("content_click_low_pct", 1.0) if page.kind == "blog" else b.get("click_low_pct", 4.0)


def projected_monthly_eur(page: SitePage, agg: FunnelAgg, cfg: dict) -> float:
    """What a page is worth if its click-through reached its own benchmark floor.

    A page already at or above its benchmark projects 0 - there is no leak
    to price. See docs/how-it-works.md "Design decisions" #5 and #6.
    """
    econ = cfg.get("economics", {})
    target = max(page.click_rate, page_benchmark_low(page, cfg))
    extra_clicks = ((target - page.click_rate) / 100) * page.sessions_30d
    if extra_clicks <= 0:
        return 0.0
    extra = (extra_clicks * agg.bookings_per_click * econ.get("marginal_factor", 0.5)
            * econ.get("avg_booking_value", 260))
    round_to = econ.get("round_projected_to", 100) or 1
    return round(extra / round_to) * round_to


def rank_bottleneck(pages: list[SitePage], agg: FunnelAgg, cfg: dict) -> Bottleneck | None:
    """The page with the largest recoverable monthly revenue. None if nothing leaks."""
    best: Bottleneck | None = None
    high = cfg.get("benchmarks", {}).get("click_high_pct", 6.0)
    for page in pages:
        projected = projected_monthly_eur(page, agg, cfg)
        if projected <= 0:
            continue
        if best is None or projected > best.projected_eur:
            best = Bottleneck(stage="Session -> booking-engine click", page_slug=page.slug,
                              rate=page.click_rate, benchmark_low=page_benchmark_low(page, cfg),
                              benchmark_high=high, projected_eur=projected)
    return best


def catalog_from_cfg(cfg: dict) -> list[CatalogEntry]:
    """Parse `config/agent.yaml: experiment_catalog:` into plain data."""
    out = []
    for row in cfg.get("experiment_catalog", []) or []:
        out.append(CatalogEntry(
            page_slug=str(row["page_slug"]), element=str(row["element"]),
            kind=str(row.get("kind", "copy")), title=str(row["title"]),
            hypothesis=str(row.get("hypothesis", "")).strip(),
            variant_a=str(row.get("variant_a", "")), variant_b=str(row.get("variant_b", ""))))
    return out


def build_proposals(catalog: list[CatalogEntry], pages: dict[str, SitePage], agg: FunnelAgg,
                    active_pairs: set[tuple[str, str]], running_count: int, cfg: dict
                    ) -> tuple[list[Proposal], list[Suppressed]]:
    """Walk the catalog once, gate each entry, return what to propose and what to skip.

    An entry is silently dropped (not even "suppressed") when its page is not
    in this export, or when the pair is already the subject of a running or
    undecided test - see docs/how-it-works.md "Step 5". Only the SEO gate
    produces a visible `Suppressed` line; the rest just do not fire.
    """
    rules = cfg.get("rules", {})
    cap = cfg.get("max_concurrent_experiments", 2)
    proposals: list[Proposal] = []
    suppressed: list[Suppressed] = []
    for entry in catalog:
        page = pages.get(entry.page_slug)
        if page is None or (entry.page_slug, entry.element) in active_pairs:
            continue
        if page.kind == "blog" and not rules.get("seo_watch", True):
            suppressed.append(Suppressed(entry.page_slug, entry.element, entry.title,
                                         "SEO watch is off by rule - content proposals paused"))
            continue
        projected = projected_monthly_eur(page, agg, cfg)
        if projected <= 0:
            continue
        voice_note = (cfg.get("brand_voice_note", "").strip()
                      if entry.kind == "copy" and rules.get("brand_voice_lock", True) else None)
        blocked = (f"At the {cap}-test cap - decide a running test first"
                  if rules.get("max_2_concurrent", True) and running_count >= cap else None)
        proposals.append(Proposal(
            page_slug=entry.page_slug, element=entry.element, kind=entry.kind, title=entry.title,
            hypothesis=entry.hypothesis, variant_a=entry.variant_a, variant_b=entry.variant_b,
            projected_eur=projected, voice_note=voice_note, blocked_reason=blocked))
    return proposals, suppressed


def run_funnel_analysis(daily: list[DailyRow], pages: list[SitePage], catalog: list[CatalogEntry],
                        active_pairs: set[tuple[str, str]], running_count: int, cfg: dict,
                        currency: str = "EUR") -> AnalysisResult:
    """Compose every step above into one result, with a human-readable thinking log."""
    window_days = cfg.get("window_days", 30)
    agg = aggregate_funnel(daily, window_days)
    verdicts = judge_stages(agg, cfg)
    pages_by_slug = {p.slug: p for p in pages}
    bottleneck = rank_bottleneck(pages, agg, cfg)
    proposals, suppressed = build_proposals(catalog, pages_by_slug, agg, active_pairs,
                                            running_count, cfg)
    b = cfg.get("benchmarks", {})

    log = [
        f"Read the funnel: last {agg.days} days: {agg.reach:,} reached -> {agg.sessions:,} "
        f"sessions -> {agg.engine_clicks:,} booking-engine clicks ({agg.click_rate}%) -> "
        f"{agg.engine_searches:,} dated searches -> {agg.bookings:,} direct bookings worth "
        f"{money(agg.revenue, currency)}.",
        f"Judge each stage against benchmark: session -> engine click {agg.click_rate}% is "
        f"{verdicts['click']} ({b.get('click_low_pct', 4.0)}-{b.get('click_high_pct', 6.0)}%). "
        f"Click -> dated search {agg.search_rate}% is {verdicts['search']}. Search -> booking "
        f"{agg.book_rate}% is {verdicts['book']} "
        f"({b.get('search_book_low_pct', 25.0)}-{b.get('search_book_high_pct', 35.0)}%).",
    ]
    if bottleneck:
        log.append(f"Rank the leak: {bottleneck.page_slug} converts {bottleneck.rate}% of "
                  f"sessions into a booking-engine click against a {bottleneck.benchmark_low}% "
                  f"benchmark floor - worth about {money(bottleneck.projected_eur, currency)}/mo "
                  f"at the floor.")
    else:
        log.append("Rank the leak: every page in site_pages is already at or above its own "
                  "benchmark - nothing is leaking today.")
    cap_text = (str(cfg.get("max_concurrent_experiments", 2))
               if cfg.get("rules", {}).get("max_2_concurrent", True) else "off")
    log.append(f"Check running experiments: {running_count} in flight (cap {cap_text}).")
    if suppressed:
        log.append(f"{len(proposals)} change(s) proposed; {len(suppressed)} suppressed by rule: "
                  + "; ".join(s.title for s in suppressed) + ".")
    else:
        log.append(f"{len(proposals)} change(s) proposed. Each one is a single variable, "
                  "described for a person to implement, split 50/50.")

    if bottleneck:
        headline = (f"Biggest leak: {bottleneck.page_slug} converts only {bottleneck.rate}% of "
                   f"sessions into a booking-engine click (benchmark {bottleneck.benchmark_low}-"
                   f"{bottleneck.benchmark_high}%). {len(proposals)} fix(es) proposed, worth "
                   f"about {money(bottleneck.projected_eur, currency)}/mo at the benchmark floor.")
    else:
        headline = (f"No page is leaking against its own benchmark today. {len(proposals)} "
                   f"fix(es) still proposed from the catalog.")
    log.append(f"Decision: {headline}")

    healthy = []
    if verdicts["search"] == "healthy":
        healthy.append({"stage": "Click -> dated search",
                        "detail": f"{agg.search_rate}% of engine clicks turn into a dated "
                                 "search - healthy; no proposal."})
    if verdicts["book"] in ("healthy", "at the top of the band"):
        healthy.append({"stage": "Engine search -> booking",
                        "detail": f"{agg.book_rate}% - {verdicts['book']}. Left alone on "
                                 "purpose: the engine converts, the site does not feed it."})

    summary = {
        "headline": headline, "click_rate": agg.click_rate, "search_rate": agg.search_rate,
        "book_rate": agg.book_rate, "bottleneck_page": bottleneck.page_slug if bottleneck else None,
        "projected_eur": bottleneck.projected_eur if bottleneck else 0.0,
        "proposal_count": len(proposals), "suppressed_count": len(suppressed),
    }
    return AnalysisResult(thinking_log=log, agg=agg, bottleneck=bottleneck, proposals=proposals,
                          suppressed=suppressed, healthy=healthy, summary=summary)


# --------------------------------------------------------------------------
# Track B: scoring a running experiment
# --------------------------------------------------------------------------
@dataclass
class ExperimentArm:
    """One variant's accumulated daily results for a running experiment."""

    variant: str          # "a" (control) | "b" (variant)
    sessions: int = 0
    clicks: int = 0
    bookings: int = 0

    @property
    def click_rate(self) -> float:
        return pct(self.clicks, self.sessions)

    @property
    def booking_rate(self) -> float:
        return pct(self.bookings, self.sessions)


@dataclass
class ExperimentStats:
    days: int
    a: ExperimentArm
    b: ExperimentArm
    z: float
    confidence: float
    significant: bool
    click_lift: float
    booking_lift: float


def _normal_cdf(z: float) -> float:
    """Standard normal CDF via the Abramowitz-Stegun erf approximation."""
    sign = 1.0 if z >= 0 else -1.0
    z = abs(z) / math.sqrt(2)
    t = 1.0 / (1.0 + 0.3275911 * z)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
              + 0.254829592) * t * math.exp(-z * z)
    return 0.5 * (1.0 + sign * y)


def experiment_stats(a: ExperimentArm, b: ExperimentArm, days: int,
                     significance_bar_pct: float = 95.0) -> ExperimentStats:
    """A real two-proportion z-test on click-through, plus a booking-rate lift.

    Ported faithfully from the source spec - this is genuine statistics, not
    demo fiction. `days` is how many distinct days of data fed this call; the
    caller decides whether that is enough (`min_days_running`).
    """
    p1 = a.clicks / a.sessions if a.sessions else 0.0
    p2 = b.clicks / b.sessions if b.sessions else 0.0
    total = a.sessions + b.sessions
    pooled = (a.clicks + b.clicks) / total if total else 0.0
    se = (math.sqrt(pooled * (1 - pooled) * (1 / a.sessions + 1 / b.sessions))
         if a.sessions and b.sessions else 0.0)
    z = (p2 - p1) / se if se > 0 else 0.0
    confidence = round(_normal_cdf(abs(z)) * 1000) / 10
    click_lift = round(((p2 - p1) / p1) * 100, 1) if p1 else 0.0
    booking_lift = (round(((b.booking_rate - a.booking_rate) / a.booking_rate) * 100, 1)
                    if a.booking_rate else 0.0)
    return ExperimentStats(days=days, a=a, b=b, z=round(z, 2), confidence=confidence,
                           significant=confidence >= significance_bar_pct,
                           click_lift=click_lift, booking_lift=booking_lift)


def can_publish(stats: ExperimentStats, cfg: dict) -> tuple[bool, str]:
    """Both statistical significance AND a positive lift are required.

    See docs/how-it-works.md "Design decisions" #3: a variant that is
    significantly *worse* can never clear this gate, in any configuration.
    """
    rules = cfg.get("rules", {})
    bar = cfg.get("significance_bar_pct", 95.0)
    if stats.click_lift <= 0:
        return False, f"variant B is not beating control ({stats.click_lift:+.1f}%)"
    if not rules.get("significance_95", True):
        return True, "significance_95 rule is off - only the direction check applies"
    if not stats.significant:
        return False, f"{stats.confidence}% confidence - below the {bar}% bar"
    return True, f"{stats.confidence}% confidence, {stats.click_lift:+.1f}% click-through lift"


def measured_monthly_eur(stats: ExperimentStats, page: SitePage, cfg: dict) -> float:
    """The booking-rate delta between the arms, applied to the page's full monthly traffic."""
    econ = cfg.get("economics", {})
    delta = (stats.b.booking_rate - stats.a.booking_rate) / 100
    round_to = econ.get("round_measured_to", 50) or 1
    return round(delta * page.sessions_30d * econ.get("avg_booking_value", 260) / round_to) * round_to


def classify_decision(stats: ExperimentStats, cfg: dict) -> tuple[bool, str | None]:
    """(auto, hold_reason). `auto` is True only when the gate passes, the lift is not a
    "big swing" that always needs a person, and `rules.auto_rollout` is on.

    See docs/how-it-works.md "Design decisions" #8. Even when `auto` is True
    here, the write still goes through `core.review`'s guard - `mode: shadow`
    or `review.require_approval_for` in `config/hotel.yaml` can still hold it.
    """
    ok, reason = can_publish(stats, cfg)
    if not ok:
        return False, reason
    big = cfg.get("big_swing_pct", 25.0)
    if abs(stats.click_lift) >= big:
        return False, f"big swing ({stats.click_lift:+.1f}%) - always reviewed by a person"
    if not cfg.get("rules", {}).get("auto_rollout", False):
        return False, "waiting for review (auto_rollout is off)"
    return True, None
