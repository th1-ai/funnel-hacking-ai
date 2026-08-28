# Workflow: working the review queue

Objective: work through everything waiting for a human, in plain language,
without pasting raw JSON at anyone.

## The two kinds of item

`experiment_start` - a proposal from the daily analysis. Approving and
sending means "Apply change": tell a person to start the 50/50 test.

`experiment_decision` - a running experiment that now has enough data to
score. Approving and sending means "Approve and push": tell a person to make
the variant the new control, and log it. Rejecting means "Dismiss": the
control stays.

## Steps

1. **List what is waiting.**
   ```bash
   python3 tools/review.py list
   python3 tools/review.py list --kind experiment_decision
   python3 tools/review.py list --status pending_review
   ```

2. **Show one, and explain it.**
   ```bash
   python3 tools/review.py show <id>
   ```
   For a start: name the page, the element, both variants in plain English,
   the projected euro value, and any brand-voice note or concurrency-cap
   block. For a decision: name the click-through move, the confidence, and
   the measured euro value - and say plainly whether it is being held for
   review because of the significance bar or because it is a big swing.

3. **Get the human's decision**, then act on it:
   ```bash
   python3 tools/review.py approve <id> [--note "..."]
   python3 tools/review.py edit <id> --variant-b "New wording" [--variant-a "..."] [--title "..."]
   python3 tools/review.py reject <id> --reason "..."
   ```
   `edit` only makes sense on an `experiment_start` - there is nothing to
   edit on a decision, only approve or reject it.

4. **Send what was approved.**
   ```bash
   python3 tools/review.py send
   ```
   In `mode: shadow` this reports "blocked... nothing leaves in shadow
   mode" for every item - the approval is recorded, nothing more, until
   `workflows/90-go-live.md`.

5. **A blocked send is not a failure.** `blocked <id> (approval kept)` means
   the mode stopped it, not that anything went wrong - the approval stands
   and will send once you go live. A `failed <id>` (a real adapter error)
   can be retried: `python3 tools/review.py retry <id>`.

## The concurrency cap

`python3 tools/review.py approve` on an `experiment_start` checks the
2-test cap itself and refuses outright if you are already at it:

```
blocked: at the 2-test cap - decide a running test first (reject or push one, then try again).
```

This is a real refusal, not just a note - decide (or dismiss) a running
test first, then approve the new one.
