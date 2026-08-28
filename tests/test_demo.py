"""tests/test_demo.py - `make demo`'s two guarantees, regression-tested.

FAIL Finding 2 (2026-08-27 simulation): once a hotel had written their own
`data/imports/funnel_daily.csv` / `site_pages.csv` (exactly what
`workflows/00-setup.md` step 6 tells them to do), `make demo`'s numeric
bullets picked up their real numbers while the growth-note prose - routed
through the `mock` LLM provider's canned fixture - stayed Hotel Aurora's
original text. The two halves of one `make demo` run disagreed with each
other. Root cause: `tools/ingest.py` always checked `data/imports/*.csv`
before `fixtures/inbound/*.csv`, with no branch on demo mode.

Fixed by giving `tools.ingest` an explicit `source` argument - `tools/demo.py`
now calls `one_pass(..., demo=True)`, which forces every ingest read to
`source="demo"`: fixtures/inbound only, `data/imports/` never even
consulted. These tests prove both halves of that fix: the decoy numbers
never leak in, and the two things `make demo` prints (the note, and the
numbers the note is supposedly summarising) never disagree.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings, repo_root  # noqa: E402
from core.store import Store  # noqa: E402
from tools.run import one_pass  # noqa: E402

# The real fixtures/inbound/funnel_daily.csv sums to 74,876 reached and a
# EUR 400/mo homepage leak (see tests/test_run_loop.py, tools/demo.py). A
# decoy this far off proves the fixture numbers, not the decoy, drove the
# output - a near-identical decoy could pass by coincidence.
DECOY_FUNNEL_DAILY = (
    "date,source,reach,sessions,engine_clicks,engine_searches,bookings,revenue\n"
    "2026-08-01,direct,999999,500000,400000,390000,90000,54000000\n"
)
DECOY_SITE_PAGES = (
    "slug,title,path,kind,sessions_30d,engine_clicks_30d,sort\n"
    "home,Decoy Homepage,/,page,500000,400000,0\n"
)


def _plant_decoy_imports() -> None:
    """Write wildly different numbers to `data/imports/` - the sandboxed
    repo `tests/conftest.py` gives every non-core test, never the real
    working copy. `make demo` must act as if these files do not exist.
    """
    imports_dir = repo_root() / "data" / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    (imports_dir / "funnel_daily.csv").write_text(DECOY_FUNNEL_DAILY, encoding="utf-8")
    (imports_dir / "site_pages.csv").write_text(DECOY_SITE_PAGES, encoding="utf-8")


def test_demo_never_reads_data_imports(tmp_path, capsys):
    """Regression for FAIL Finding 2, half one: decoy `data/imports/*.csv`
    numbers must never reach `make demo`'s output.
    """
    _plant_decoy_imports()

    settings = load_settings(demo=True)
    store = Store(settings, path=tmp_path / "demo-test.db")
    code, stats = one_pass(settings, store, provider="mock", today="2026-09-15", demo=True)
    store.close()
    out = capsys.readouterr().out

    assert code == 0
    assert stats["processed"] > 0
    for decoy_marker in ("999,999", "500,000", "400,000", "Decoy Homepage"):
        assert decoy_marker not in out, f"decoy data/imports/ leaked into make demo: {decoy_marker!r}"
    # The bundled Hotel Aurora fixture numbers show up instead.
    assert "74,876" in out
    assert "EUR 400" in out


def test_demo_note_and_numbers_never_disagree(tmp_path, capsys):
    """Regression for FAIL Finding 2, half two: the growth-note prose (the
    `mock` provider's canned fixture) and the numeric bullets printed right
    below it must describe the same run - the exact contradiction the
    simulation caught ("EUR 400" in the note vs "EUR 600" in the bullets).
    Planting the same decoy data makes sure this holds even when
    `data/imports/` is present, not only on a pristine clone.
    """
    _plant_decoy_imports()

    settings = load_settings(demo=True)
    store = Store(settings, path=tmp_path / "demo-test.db")
    code, _stats = one_pass(settings, store, provider="mock", today="2026-09-15", demo=True)
    store.close()
    out = capsys.readouterr().out

    assert code == 0
    assert "Growth note:" in out
    note_line = next(line for line in out.splitlines() if line.startswith("Growth note:"))
    rank_line = next(line for line in out.splitlines() if line.strip().startswith("- Rank the leak"))
    # Both halves quote the same projected monthly figure for the same page.
    assert "EUR 400" in note_line
    assert "EUR 400" in rank_line
    assert "3.0%" in note_line
    assert "3.0%" in rank_line
