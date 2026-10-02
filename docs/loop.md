# Delivery loop

This repo runs the delivery loop from the `ouroboros` plugin. The loop is the same in every
repo. What only this repo knows — how to build and verify, its language, its traps — is in the
repo itself: its CLAUDE.md, README, contributing guide, CI config. Read it there; don't guess it
from another repo, and don't ask the stakeholder what the repo already says.

Every role and convention is reachable from any shell: `loop-doc <name>` prints it. The roles
are skills of the plugin: `ouroboros:project-manager`, `ouroboros:architect`,
`ouroboros:product-owner`, `ouroboros:triage`, `ouroboros:agent-designer`.
Developer and Reviewer are subagent types, `ouroboros:developer` and
`ouroboros:reviewer`.

## Units of work

Work enters the loop as one of three units, whichever arrives. The repo decides only which
exist: no `docs/roadmap.md`, no roadmap steps.

- **A roadmap step**, `M<N>.<k>` — only in a repo that keeps `docs/roadmap.md`
  (`loop-doc roadmap`). The step text is the spec.
- **An issue**, `#<n>` — the issue is the spec. A large one is an epic the Product Owner cuts.
- **An order** — a task given in the chat, without tracker. The stakeholder's words are the spec,
  and the Architect writes them down sharpened before anything is cut.

The chain is the same for all three. What differs is only where the spec lives and where the
record goes.

## The chain

Stakeholder ⇄ Project Manager (only with a roadmap: milestone level, owns `docs/roadmap.md`) →
Architect (concept: what the unit rests on — the decisions, the terms, the sharpened spec) →
Product Owner (cuts the unit into pieces of work, spawns Developer and Reviewer) → Developer
(implements one piece, or stops) ⇄ Reviewer (gates the draft before it becomes a PR; the
Product Owner runs that round, not the Developer) → QA (the stakeholder's review, may itself
escalate to the Architect) → back to the Product Owner, and with a roadmap on to the Project
Manager once a whole step is done.

The Architect is one role in two directions — concept before the cut, refinement after a stop —
and owns the repo's rules for code. Developer runs always work in a git worktree. Triage sits
outside the loop and decides whether an issue that didn't come out of it enters it at all — a
dialogue with the stakeholder, and only where the repo's tracker has the triage labels.

The Agent-Designer sits outside it too and owns how the loop itself works: the role definitions
in this plugin, measured across every repo that runs it. It adjusts or proposes roles strictly
and only on measured patterns, and it works in the plugin's own repo, never in a project.

## Permissions

Code on a branch is always allowed. Everything else the loop could leave in the repo — issues,
labels, ADRs, `CONTEXT.md`, PR replies, even pushing — is asked **once**, and the answer is
remembered with `loop-permission <kind> <yes|no>` before the write happens. A `no` moves its
record elsewhere (`loop-doc permissions`). Never write a kind that is `no`, and never ask again
for one that is decided. Below this text, the session start lists what is decided here.

## Decide or abort

Every role in the loop decides for itself and stops only for what isn't its to decide. An abort
names its **receiver**, not an error class — there are three:

- **What holds** — a spec that doesn't say, a decision that contradicts, a rule for code that
  looks wrong → **Architect**. Parked as `needs-refinement` where labels are allowed.
- **Whether it's due now** — priority, scope, a result that no longer matches the goal →
  **Triage** on an issue, the stakeholder on everything else.
- **How it's cut, and in what order** — a piece that belongs to a series, a unit that needs
  splitting → **Product Owner**.

Where `issues` is not allowed, an abort is a report to whoever spawned the role,
naming the receiver — the session carries it instead of a label. The Architect is the last
authority on what holds: its own abort goes to the stakeholder. Triage never aborts — it is a
dialogue by definition and proposes instead.

Aborting is a normal outcome. Guessing at another receiver's question is the failure.

## Triggers

The stakeholder names a unit or a level and means "act as that role" — no need to also say "you
are the X". Each trigger comes in English and in German, and both mean the same. "we're working
on \<X>" / "wir bearbeiten \<X>" is the same trigger as "continue with \<X>" / "weiter mit \<X>" —
the wording below is a short form, not a password. Each trigger loads the role's skill.

- "continue with M\<N>" / "weiter mit M\<N>" → Project Manager — strategy only, with a roadmap:
  an idea measured against it, or a finished step ticked off. He does not hand work out.
- "continue with M\<N>.\<k>" / "weiter mit M\<N>.\<k>" → Architect, concept stage of that roadmap
  step. Naming it *is* the priority call — yours, not a session's. A dialogue: the Architect
  does its reading alone and then grills you. With nothing to decide it hands on to the Product
  Owner in the same session.
- "continue with #\<n>" / "weiter mit #\<n>" → read the issue fresh (`gh issue view <n>
  --comments`). Where the repo uses the loop's labels, they decide: `ready-for-agent` → Product
  Owner, `needs-refinement` → Architect, `needs-triage` → Triage, anything else → ask which
  role. Where it doesn't, the issue is a new unit → Architect, concept stage. A closed issue is
  done; report that instead.
- "order: \<text>" / "auftrag: \<text>", or any task you give as the work to do → an order →
  Architect, concept stage. It writes the sharpened spec back to you before anything is cut.
- "cut \<unit>" / "schnitt \<unit>" → Product Owner, cutting that unit — after its concept is
  settled.
- "close out M\<N>.\<k>" / "abschluss M\<N>.\<k>" → Product Owner, close-out of a roadmap step.
  The `SessionStart` hook reports on its own when this is due.
- "review on #\<n>" / "review zu #\<n>" → Product Owner, who spawns the Developer in the worktree
  its branch still sits in, with your feedback on the open PR.
- "continue with agents" / "weiter mit Agents" → Agent-Designer, in a session in the plugin's
  repo. Said in a project session, it names the plugin repo and stops.

The Developer never runs as the session itself. The review gate needs someone above it who
didn't write the draft, and in a Developer session nobody is.
