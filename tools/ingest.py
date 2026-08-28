"""tools/ingest.py - the signals no adapter covers: web analytics, the site-page
catalog, SEO rank data, the cross-agent OTA read, and the A/B testing tool's
own daily results.

No adapter in `core/adapters/` covers a web analytics platform, a booking
engine's funnel data, an SEO rank tracker or an A/B testing tool - see
docs/how-it-works.md "Design decisions" #1 and docs/integrations.md. Every
function here reads the same shape two ways, controlled by its explicit
``source`` argument:

- ``source=None`` (the default - a real `tools/run.py` pass or `make
  doctor`): `data/imports/<name>.csv` first (your own export, or a script
  you point at your analytics/testing tool), `fixtures/inbound/<name>.csv`
  second.
- ``source="demo"`` (only `tools/demo.py`): `fixtures/inbound/<name>.csv`
  ONLY. `data/imports/` is never even looked at, let alone read - this is
  what keeps `make demo` immune to a hotel's own connected data, whatever
  is sitting in `data/imports/` at the time. See docs/how-it-works.md
  "Design decisions" and `tools/demo.py`'s module docstring.

Both return the same list of dataclasses either way, so `tools/funnel_engine.py`
never knows or cares which one supplied them.

The import/fixture directories are resolved fresh on every call (never
cached at import time) so that `AGENT_REPO_ROOT` - set by `tests/conftest.py`
for every non-core test, and honoured by `core.config.repo_root()` - always
takes effect, even though this module is imported once per test process.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.config import repo_root
from tools.funnel_engine import CatalogEntry, DailyRow, ExperimentArm, SitePage

SIGNALS = ("funnel_daily", "site_pages", "seo_keywords", "ota_content_findings",
          "ota_listings", "funnel_experiment_daily")

DEMO_SOURCE = "demo"


def _dirs() -> tuple[Path, Path]:
    """(imports dir, fixtures dir), resolved against the current `repo_root()`."""
    root = repo_root()
    return root / "data" / "imports", root / "fixtures" / "inbound"


def _rows(name: str, *, source: str | None = None) -> list[dict]:
    """Read one signal's rows. See the module docstring for what ``source`` does."""
    imports_dir, inbound_dir = _dirs()
    bases = (inbound_dir,) if source == DEMO_SOURCE else (imports_dir, inbound_dir)
    for base in bases:
        path = base / f"{name}.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                return [dict(row) for row in csv.DictReader(fh)]
    return []


def source_used(name: str, *, source: str | None = None) -> str:
    imports_dir, inbound_dir = _dirs()
    if source != DEMO_SOURCE and (imports_dir / f"{name}.csv").exists():
        return f"data/imports/{name}.csv"
    if (inbound_dir / f"{name}.csv").exists():
        return f"fixtures/inbound/{name}.csv (demo data)"
    return "none - defaults to empty"


def sources_used() -> dict[str, str]:
    """Which source each signal is actually reading from - for `make doctor`.

    Never called with ``source="demo"`` - `make doctor` reports on the real
    working copy, never the demo path.
    """
    return {name: source_used(name) for name in SIGNALS}


def load_funnel_daily(name: str = "funnel_daily", *, source: str | None = None) -> list[DailyRow]:
    out = []
    for row in _rows(name, source=source):
        out.append(DailyRow(
            date=str(row.get("date", "")).strip(), source=str(row.get("source", "")).strip(),
            reach=int(float(row.get("reach", 0) or 0)), sessions=int(float(row.get("sessions", 0) or 0)),
            engine_clicks=int(float(row.get("engine_clicks", 0) or 0)),
            engine_searches=int(float(row.get("engine_searches", 0) or 0)),
            bookings=int(float(row.get("bookings", 0) or 0)),
            revenue=float(row.get("revenue", 0) or 0)))
    return out


def load_site_pages(name: str = "site_pages", *, source: str | None = None) -> list[SitePage]:
    out = []
    for i, row in enumerate(_rows(name, source=source)):
        out.append(SitePage(
            slug=str(row.get("slug", "")).strip(), title=str(row.get("title", "")).strip(),
            path=str(row.get("path", "")).strip(), kind=str(row.get("kind") or "page").strip(),
            sessions_30d=int(float(row.get("sessions_30d", 0) or 0)),
            engine_clicks_30d=int(float(row.get("engine_clicks_30d", 0) or 0)),
            sort=int(float(row.get("sort", i) or i))))
    return out


def load_seo_keywords(name: str = "seo_keywords", *, source: str | None = None
                      ) -> list[dict[str, Any]]:
    """Analytics only - never feeds a proposal. See docs/how-it-works.md #12."""
    out = []
    for row in _rows(name, source=source):
        out.append({
            "keyword": str(row.get("keyword", "")).strip(),
            "position": int(float(row.get("position", 0) or 0)),
            "prev_position": int(float(row.get("prev_position", 0) or 0)),
            "volume": int(float(row.get("volume", 0) or 0)),
            "clicks_mo": int(float(row.get("clicks_mo", 0) or 0)),
            "url": str(row.get("url", "")).strip(), "note": str(row.get("note") or ""),
        })
    return out


def load_ota_content_findings(name: str = "ota_content_findings", *, source: str | None = None
                              ) -> list[dict[str, Any]]:
    """Cross-agent, read-only - see docs/how-it-works.md #11. Never written here."""
    out = []
    for row in _rows(name, source=source):
        out.append({"channel": str(row.get("channel", "")).strip(),
                    "kind": str(row.get("kind", "")).strip(),
                    "detail": str(row.get("detail", "")).strip(),
                    "severity": str(row.get("severity", "medium")).strip() or "medium"})
    return out


def load_ota_listings(name: str = "ota_listings", *, source: str | None = None
                      ) -> list[dict[str, Any]]:
    """Cross-agent, read-only. One row per channel: a health note for the OTA-referral row."""
    out = []
    for row in _rows(name, source=source):
        out.append({"channel": str(row.get("channel", "")).strip(),
                    "health_pct": int(float(row.get("health_pct", 100) or 100)),
                    "note": str(row.get("note") or "")})
    return out


def load_experiment_daily(name: str = "funnel_experiment_daily", *, source: str | None = None
                          ) -> dict[tuple[str, str], dict[str, ExperimentArm | int]]:
    """Group the testing tool's daily export into one A/B pair per (page_slug, element).

    Returns ``{(page_slug, element): {"a": ExperimentArm, "b": ExperimentArm, "days": n}}``
    - `days` is the count of distinct `day_offset` values seen, which is what
    `min_days_running` is compared against.
    """
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _rows(name, source=source):
        key = (str(row.get("page_slug", "")).strip(), str(row.get("element", "")).strip())
        variant = str(row.get("variant", "")).strip().lower()
        if variant not in ("a", "b") or not key[0]:
            continue
        bucket = buckets.setdefault(key, {"a": ExperimentArm("a"), "b": ExperimentArm("b"),
                                          "day_offsets": set()})
        arm: ExperimentArm = bucket[variant]
        arm.sessions += int(float(row.get("sessions", 0) or 0))
        arm.clicks += int(float(row.get("clicks", 0) or 0))
        arm.bookings += int(float(row.get("bookings", 0) or 0))
        bucket["day_offsets"].add(str(row.get("day_offset", "")))
    return {key: {"a": b["a"], "b": b["b"], "days": len(b["day_offsets"])}
           for key, b in buckets.items()}


def catalog_from_settings(settings: Any) -> list[CatalogEntry]:
    """`config/agent.yaml: experiment_catalog:` - see tools/funnel_engine.catalog_from_cfg."""
    from tools.funnel_engine import catalog_from_cfg
    return catalog_from_cfg(settings.agent)
