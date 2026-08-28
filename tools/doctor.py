#!/usr/bin/env python3
"""tools/doctor.py - is Funnel Hacking AI configured and reachable right now?

    make doctor
    python3 tools/doctor.py

Runs the generic core.doctor checks (python, deps, config, .env, hotel
identity, mode, llm provider, every adapter, the store, knowledge) plus this
agent's own: the experiment catalog, the prompt files, and which file is
actually feeding each signal (docs/how-it-works.md "Step 1"). Exits 0 when
everything passed, 1 when a FAIL line needs fixing. Never a traceback: a
config error is shown as a FAIL row like any other.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.doctor import Check, FAIL, PASS, WARN, print_table, run_checks  # noqa: E402
from tools import ingest  # noqa: E402


def check_catalog(settings: Settings) -> Check:
    catalog = settings.agent_get("experiment_catalog", [])
    if not catalog:
        return Check("experiment catalog", FAIL, "config/agent.yaml has no experiment_catalog",
                     "This agent never invents copy - add at least one row (see "
                     "config/agent.example.yaml) so it has something to propose.")
    pages = {row.get("page_slug") for row in catalog}
    return Check("experiment catalog", PASS,
                 f"{len(catalog)} entr{'y' if len(catalog) == 1 else 'ies'} across "
                 f"{len(pages)} page(s)")


def check_signals() -> Check:
    sources = ingest.sources_used()
    missing = [name for name, src in sources.items() if src.startswith("none")]
    detail = ", ".join(f"{name}={src.split('/')[-1] if '/' in src else src}"
                       for name, src in sources.items())
    if missing:
        return Check("signal sources", WARN, f"{detail}",
                     f"{', '.join(missing)} defaulting to empty - see docs/integrations.md "
                     "for the CSV columns each one needs.")
    return Check("signal sources", PASS, detail)


def check_prompts() -> Check:
    missing = [p for p in ("prompts/funnel_note.md", "prompts/schemas/funnel_note.json")
              if not (REPO_ROOT / p).is_file()]
    if missing:
        return Check("prompts", FAIL, f"missing {', '.join(missing)}",
                     "These ship with the repo - restore them from git.")
    return Check("prompts", PASS, "funnel_note.md + schema present")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        checks = run_checks(None) + [Check("config", FAIL, str(exc),
                                           "Fix config/hotel.yaml or config/agent.yaml.")]
        return print_table(checks, title="Funnel Hacking AI - doctor")

    checks = run_checks(settings, extra=[check_catalog])
    checks.append(check_signals())
    checks.append(check_prompts())
    return print_table(checks, title="Funnel Hacking AI - doctor")


if __name__ == "__main__":
    raise SystemExit(main())
