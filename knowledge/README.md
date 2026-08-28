# knowledge/

This folder is the agent's memory of your property. Most agents in this
family read these files before drafting anything a guest sees. **Funnel
Hacking AI is different: nothing here is read by a prompt.** This agent
sends no guest-facing text and no guest inbox exists for it, so
`property.md`/`faq.md`/`signature.md` below are the generic scaffold
templates, shipped for consistency across the family, and are optional for
this repo specifically. `brand-voice.md` is the one file that actually
matters here - a short, plain reference for the tone check
`rules.brand_voice_lock` points a person back to.

## What to put here

| File | What it holds |
|---|---|
| `brand-voice.md` | **This agent's own.** A few sentences of what your property's copy sounds like (and does not sound like), so a person can check a proposed variant against it before shipping it. See `knowledge/brand-voice.example.md`. |
| `property.md` | Generic scaffold template. Not read by this agent. |
| `faq.md` | Generic scaffold template. Not read by this agent. |
| `signature.md` | Generic scaffold template. Not read by this agent - Funnel Hacking AI sends no messages a guest ever sees. |

Copy the file that actually matters here:

```bash
cp knowledge/brand-voice.example.md knowledge/brand-voice.md
```

`knowledge/*.md` is gitignored (the `.example.md` files are not), because
your property notes are yours.

## How to write `brand-voice.md`

**Write it the way you would brief a new marketing hire.** Three or four
sentences: the tone you want (warm, direct, understated - whatever is
true), a couple of words or phrases you never use, and one example of
copy that sounds right.

**This is a check for a human, not a filter in code.** `rules.brand_voice_lock`
attaches a note to any copy proposal, pointing here - see
`docs/how-it-works.md` "Design decisions" #9. Nothing in this repo enforces
tone automatically; a person still reads the proposed copy against this
file before approving it.

## Keeping it current

Update this file whenever the property's voice shifts - a rebrand, a new
market, a season with a different tone. A brand-voice note nobody has
touched in a year is worth a five-minute re-read before the next test
ships.
