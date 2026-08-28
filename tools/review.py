#!/usr/bin/env python3
"""tools/review.py - work the review queue: list / show / approve / edit / reject / send.

    python3 tools/review.py list [--status pending_review] [--kind experiment_start]
    python3 tools/review.py show <id>
    python3 tools/review.py approve <id> [--note "..."]
    python3 tools/review.py edit <id> --variant-b "New copy" [--variant-a "..."] [--note "..."]
    python3 tools/review.py reject <id> --reason "not this quarter"
    python3 tools/review.py retry <id>          # re-queue a failed send
    python3 tools/review.py stale               # go-live only: clear the shadow backlog
    python3 tools/review.py send                # send everything approved/edited

Only this tool writes `approved` / `edited` / `rejected` (core/review.py). Only
`send` writes `sending` / `sent`. Nothing here bypasses `mode: shadow` - see
docs/safety.md.

Item kinds in this repo: `experiment_start` (a proposal - approving and
sending means "Apply change": `messaging.notify_staff()` tells a person to
start the test) and `experiment_decision` (a scored, running experiment -
approving and sending means "Approve and push": `messaging.notify_staff()`
+ `sheets.append()`; rejecting means "Dismiss", the control stays).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging, get_sheets  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.review import (WriteBlocked, approve, edit, list_queue, reject, retry, show,  # noqa: E402
                         stale_backlog)
from core.store import Store, StoreError  # noqa: E402
from tools.run import _publish_decision, _publish_start, _running_pairs  # noqa: E402


def _print_item_line(item) -> None:
    p = item.payload or {}
    marker = "  [SAMPLE DATA]" if item.is_sample else ""
    if item.kind == "experiment_start":
        what = (f"{p.get('page_slug','')}/{p.get('element','')}  "
               f"A:{str(p.get('variant_a',''))[:22]} -> B:{str(p.get('variant_b',''))[:22]}")
        if p.get("blocked_reason"):
            what += "  [at cap]"
    elif item.kind == "experiment_decision":
        what = (f"{p.get('page_slug','')}/{p.get('element','')}  "
               f"lift {p.get('click_lift', 0):+.1f}%  confidence {p.get('confidence', 0)}%")
    else:
        what = json.dumps(p)[:60]
    print(f"  {item.id}  {item.review_status:<14} {item.kind:<20} {what[:70]}{marker}".rstrip())


def cmd_list(store, args) -> int:
    items = list_queue(store, status=args.status, kind=args.kind, limit=args.limit)
    if not items:
        print("Nothing is waiting for you.")
        return 0
    print(f"{len(items)} item(s) waiting:\n")
    for item in items:
        _print_item_line(item)
    if any(item.is_sample for item in items):
        print("\n[SAMPLE DATA] One or more items above were built from the shipped "
             "sample fixtures, not your property - systems.messaging.adapter is 'mock'. "
             "Connect your systems in config/hotel.yaml (see docs/integrations.md) "
             "before approving them.")
    print("\nRun `python3 tools/review.py show <id>` for the full detail and its reason.")
    return 0


def cmd_show(store, settings, args) -> int:
    try:
        detail = show(store, args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    item = detail["item"]
    draft = item.get("draft") or {}
    currency = settings.hotel.currency
    if (item.get("payload") or {}).get("_sample"):
        print("[SAMPLE DATA] This item was built from the shipped sample fixtures, not "
             "your property - systems.messaging.adapter is 'mock'. Connect your systems "
             "in config/hotel.yaml (see docs/integrations.md) before approving it.\n")
    print(json.dumps(item, indent=2, ensure_ascii=False, default=str))
    if item["kind"] == "experiment_start":
        if draft.get("voice_note"):
            print(f"\nBrand voice note: {draft['voice_note']}")
        if draft.get("blocked_reason"):
            print(f"\nCannot start yet: {draft['blocked_reason']}")
        if draft.get("projected_eur"):
            print(f"\nProjected: about {currency} {draft['projected_eur']:,.0f}/mo at the "
                 "benchmark floor.")
    if item["kind"] == "experiment_decision":
        print(f"\nWhy: {draft.get('a_click_rate')}% -> {draft.get('b_click_rate')}% click-through "
             f"over {draft.get('days')} days, {draft.get('confidence')}% confidence "
             f"(z={draft.get('z')}). Booking-rate moved {draft.get('booking_lift', 0):+.1f}%.")
        if draft.get("measured_text"):
            print(f"Measured: about {draft['measured_text']}/mo at full traffic.")
    print("\nEvents:")
    for event in detail["events"]:
        print(f"  {event['ts']}  {event['actor']:<6} {event['action']}")
    return 0


def cmd_approve(store, settings, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    if item.kind == "experiment_start":
        rules = settings.agent.get("rules", {})
        cap = settings.agent.get("max_concurrent_experiments", 2)
        if rules.get("max_2_concurrent", True) and len(_running_pairs(store)) >= cap:
            print(f"blocked: at the {cap}-test cap - decide a running test first "
                 "(reject or push one, then try again).", file=sys.stderr)
            return 1
    updated = approve(store, args.id, note=args.note or "")
    print(f"approved {updated.id} - now in the send queue")
    return 0


def cmd_edit(store, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    new_draft = dict(item.draft or item.payload or {})
    changed = False
    if args.variant_a is not None:
        new_draft["variant_a"] = args.variant_a
        changed = True
    if args.variant_b is not None:
        new_draft["variant_b"] = args.variant_b
        changed = True
    if args.title is not None:
        new_draft["title"] = args.title
        changed = True
    if not changed:
        print("error: give --variant-a, --variant-b or --title", file=sys.stderr)
        return 1
    edit(store, args.id, new_draft, note=args.note or "")
    print(f"edited {item.id} - now in the send queue")
    return 0


def cmd_reject(store, args) -> int:
    item = reject(store, args.id, reason=args.reason or "")
    verb = "dismissed" if item.kind == "experiment_decision" else "rejected"
    print(f"{verb} {item.id}")
    return 0


def cmd_retry(store, args) -> int:
    item = retry(store, args.id)
    print(f"queued {item.id} for another send attempt")
    return 0


def cmd_stale(store, args) -> int:
    """Go-live only (workflows/90-go-live.md): clear whatever piled up during
    shadow mode, which was never sent and may no longer be current."""
    ids = stale_backlog(store)
    print(f"{len(ids)} item(s) moved to stale.")
    return 0


def cmd_send(store, settings, args) -> int:
    claimed = store.claim_for_send(limit=args.limit)
    if not claimed:
        print("Nothing approved or edited is waiting to send.")
        return 0
    messaging = get_messaging(settings)
    sheets = get_sheets(settings)
    sent, failed = 0, 0
    for item in claimed:
        try:
            if item.kind == "experiment_start":
                message_id = _publish_start(messaging, item)
            elif item.kind == "experiment_decision":
                message_id = _publish_decision(messaging, sheets, item)
            else:
                message_id = None
        except WriteBlocked as exc:
            # Not a failure: the mode blocked it. The approval stands for go-live.
            store.transition(item.id, "approved", "agent", {"blocked": str(exc)[:200]})
            print(f"blocked {item.id} (approval kept): {exc}")
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - record and move on, never crash the batch
            store.mark_send_failed(item.id, str(exc))
            print(f"failed {item.id}: {exc}")
            failed += 1
            continue
        store.mark_sent(item.id, message_id)
        print(f"sent {item.id}")
        sent += 1
    print(f"\n{sent} sent, {failed} failed.")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="what is waiting for a human")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--kind", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="full detail for one item")
    p_show.add_argument("id")

    p_approve = sub.add_parser("approve", help="approve unchanged (Apply change / Approve and push)")
    p_approve.add_argument("id")
    p_approve.add_argument("--note", default="")

    p_edit = sub.add_parser("edit", help="rewrite a proposal's copy, then queue it")
    p_edit.add_argument("id")
    p_edit.add_argument("--variant-a", default=None)
    p_edit.add_argument("--variant-b", default=None)
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="discard a proposal, or Dismiss a decision")
    p_reject.add_argument("id")
    p_reject.add_argument("--reason", "--note", dest="reason", default="")

    p_retry = sub.add_parser("retry", help="re-queue a failed send")
    p_retry.add_argument("id")

    sub.add_parser("stale", help="go-live step: clear the shadow-era backlog")

    p_send = sub.add_parser("send", help="send everything approved or edited")
    p_send.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    try:
        store = Store(settings)
    except StoreError as exc:
        print(f"store error: {exc}", file=sys.stderr)
        return 1
    try:
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, settings, args)
        if args.command == "approve":
            return cmd_approve(store, settings, args)
        if args.command == "edit":
            return cmd_edit(store, args)
        if args.command == "reject":
            return cmd_reject(store, args)
        if args.command == "retry":
            return cmd_retry(store, args)
        if args.command == "stale":
            return cmd_stale(store, args)
        if args.command == "send":
            return cmd_send(store, settings, args)
        parser.error(f"unknown command {args.command}")
        return 2
    except (AdapterError, StoreError, WriteBlocked) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
