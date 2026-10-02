---
name: triage
description: "Triage of the delivery loop — a dialogue with the stakeholder on whether a needs-triage issue comes now, later or never. Use on \"weiter mit #<n>\" for an issue labelled needs-triage, or when the SessionStart hook reports a parked issue as due."
---

# Triage

**Only where the repo's tracker carries the triage labels** (`loop-doc triage-labels`) and the
repo allows `labels`. Elsewhere there is no `needs-triage` door: an issue the stakeholder
names is a unit of work for the Architect, and "not now" is the stakeholder's word in the
session, not a label.

The loop contract is already in context in a repo that runs the loop (else `loop-doc loop`). What
the repo knows about itself is in its own CLAUDE.md and docs; what you may write here,
`loop-permission` shows (`loop-doc permissions`).

Decides what happens to a `needs-triage` issue: it comes now, it comes later, or it doesn't come
at all. Unlike the ouroboros roles, this one is a **dialogue** — "does this come now" is a
stakeholder call about priorities, not an agent call about code. You research it, you propose a
verdict with its reasoning, the stakeholder decides.

## Trigger

An issue labelled `needs-triage` — everything that didn't come out of the delivery loop: an
ad-hoc bug note, an observation from an architecture review, a question that wants answering
before some later milestone. Issues the Product Owner creates start at `ready-for-agent` and
never pass through here (`loop-doc triage-labels`).

## Research before you propose

The issue is a claim, not a finding. Check it before you carry it forward.

- **The code it names.** Who actually calls what, and how large is the affected surface? A
  coupling with one caller is a different problem than the same coupling with six.
- **`docs/adr/` and `CONTEXT.md`** for the area it touches (see `loop-doc domain`) — especially
  accepted-but-unimplemented decisions, which are the usual reason a change is cheaper later.
- **The plan, where the repo has one** — `docs/roadmap.md` and `docs/roadmap/m<N>.md`, or the
  open issues. Is any current or next piece of work blocked by this? Does an upcoming one touch
  the same code anyway?

What makes a proposal worth reading is a fact the issue itself doesn't have yet. Put it first.

## The verdict is the stakeholder's

Lay out the recommendation with its reasoning and name the alternative you rejected, then let
them choose. Don't relabel on a verdict they haven't confirmed — a silently parked issue and a
silently started one are the same failure in opposite directions.

Possible outcomes:

| Outcome | Label |
| ------- | ----- |
| Comes now, fully specified | `ready-for-agent` (drop `needs-triage`) |
| Comes now, but a WAS question is open first | `needs-refinement` (drop `needs-triage`) |
| Comes now, but not agent work | `ready-for-human` (drop `needs-triage`) |
| Parked with a revisit point | keep `needs-triage`, add `revisit:<trigger>` |
| Never | `wontfix`, then `gh issue close` |

Parking is the outcome that needs the most care, because it's the one that quietly becomes
"forgotten" if you leave it vague. It needs a named trigger, and that trigger needs a
milestone-shaped form so something can make it due — see `loop-doc triage-labels`.

## Record the verdict on the issue

`gh issue comment <n>`, then the labels. The comment is the record; write it so the person who
picks the issue up at its revisit point doesn't have to redo the research:

- what you checked, and the finding that decided it (not just the conclusion)
- why not now — and, for a parked issue, what would change that
- the trigger, and the backstop trigger if the real one isn't scheduled yet
- what stays valid unchanged: acceptance criteria and guardrails you did *not* touch

Don't edit the issue body to record a verdict. The body is the reporter's claim; the verdict is
a comment underneath it.

## Making a parked issue come back

`roadmap-status` reports a parked issue as due once the roadmap reaches its
`revisit:m<N>` / `revisit:m<N>.<k>` trigger, and the `SessionStart` hook puts that in front of
whoever opens the next session. That is the whole reason the trigger has to be milestone-shaped:
same argument as the `M<N>.<k>` commit prefix in `loop-doc git` — without it, a parked issue is
invisible to everything except a human who happens to remember it.

A due report is not a verdict. It reopens the dialogue; the issue goes through this doc again,
against a repo that has meanwhile changed. Part of that second pass is routing: the label only
said *when* to look again, not *what kind* of question it is. A structure question goes to the
Architect's concept stage of the step it belongs to (`revisit:m<N>.<k>`, which the Architect
collects itself — `ouroboros:architect`); a roadmap question goes to the Project Manager; a bug or a
gap becomes `ready-for-agent`. A milestone-level trigger (`revisit:m<N>`) always comes back
through here first — nobody else picks those up.
