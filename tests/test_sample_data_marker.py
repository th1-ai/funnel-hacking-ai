"""A real (not `make demo`) pass on a fresh clone reads the shipped fixtures.

`config/hotel.example.yaml` ships `systems.messaging.adapter: mock`, so an
item this agent reads through that adapter before the hotel has connected
anything is sample data, never the property's own. `core.store.Store.upsert_item`
tags it `_sample: True` (via `core.adapters.is_sample_source`; this repo does
not re-implement the tagging, only consumes it through `item.is_sample`), and
`tools/review.py` must show that as a `[SAMPLE DATA]` marker in both `list`
and `show` so nobody approves a fixture as a real experiment.

`tests/conftest.py`'s autouse fixture isolates AGENT_CONFIG_DIR/AGENT_REPO_ROOT
for every test in this module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings
from core.store import Store
from tools.review import cmd_list, cmd_show

PAYLOAD = {
    "page_slug": "home",
    "element": "hero.cta.copy",
    "title": "Homepage hero button: a sharper call to action",
    "variant_a": "Book Now",
    "variant_b": "Check today's rate",
}


def _waiting_sample_item(tmp_path):
    """One `experiment_start` waiting for a human, read on the shipped default."""
    settings = load_settings()
    assert settings.systems.messaging.adapter == "mock"  # the shipped default
    assert settings.demo is False  # the real path, not `make demo`
    store = Store(settings, path=tmp_path / "test.db")
    item = store.upsert_item(source="messaging", external_id="exp-home-hero-cta",
                             kind="experiment_start", payload=dict(PAYLOAD))
    store.transition(item.id, "dispatched", "agent")
    store.transition(item.id, "pending_review", "agent")
    return settings, store, store.get_item(item.id)


def test_a_real_pass_on_the_mock_default_tags_its_item_sample(tmp_path):
    _settings, store, item = _waiting_sample_item(tmp_path)
    store.close()
    assert item.is_sample is True
    assert item.payload.get("_sample") is True


def test_review_list_shows_the_sample_marker(tmp_path, capsys):
    _settings, store, _item = _waiting_sample_item(tmp_path)
    capsys.readouterr()  # discard anything written while setting up
    cmd_list(store, SimpleNamespace(status=None, kind=None, limit=50))
    store.close()
    out = capsys.readouterr().out
    assert "[SAMPLE DATA]" in out
    assert "not your property" in out


def test_review_show_prints_a_sample_warning_before_the_json(tmp_path, capsys):
    settings, store, item = _waiting_sample_item(tmp_path)
    capsys.readouterr()
    cmd_show(store, settings, SimpleNamespace(id=item.id))
    store.close()
    out = capsys.readouterr().out
    assert out.startswith("[SAMPLE DATA]")
