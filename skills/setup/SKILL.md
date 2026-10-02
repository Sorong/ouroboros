---
name: setup
description: "Verankert den Delivery-Loop in einem eigenen Repo — alles erlauben, Labels, Gerüst für Roadmap, ADRs, CONTEXT.md und Code-Prinzipien. Nicht nötig für fremde Repos: dort läuft der Loop ohne Einrichtung und fragt einmal, was er darf. Use when the stakeholder wants their own repo to carry the delivery loop."
disable-model-invocation: true
---

# Setup

For the stakeholder's own repo, where the loop's files may live and everyone working on it
should get the same loop. Someone else's repo needs no setup: the loop runs there as it is,
asks once what it may write, and remembers it in the clone (`loop-doc permissions`).

Read `loop-doc loop` first. A dialogue: find out alone what the repo already says, then ask the
stakeholder the rest, one question at a time, each with your proposal.

## 1. Find out, alone

- The remote, whether `gh` reaches it, whether the tracker is GitHub, which labels exist.
- The language the repo writes docs and commits in, and its commit convention.
- How it builds and verifies, and what a fresh worktree lacks before that works (an engine's
  cache, `node_modules`, a generated file). Run the verify command once if it is cheap.
- What it already keeps: `docs/roadmap.md`, ADRs, `CONTEXT.md`, code rules, a contributing guide.

## 2. Write what the repo should say about itself into its CLAUDE.md

Only what is missing there, and only what a role would otherwise have to guess: how to verify
and from where, what is generated and must not be hand-edited, what a fresh worktree needs, how
a visible result is proven, the language of docs and code. This is the repo's own knowledge —
it stays useful without the plugin.

## 3. Decide the permissions for everyone

`.claude/ouroboros.json`, usually `{"permissions": {"*": "yes"}}` — the repo carries the
loop, so nobody is asked. Name a kind with `"no"` where the stakeholder wants it kept out.
Thresholds for the checks go in the same file (`loop-doc house-style`).

## 4. Scaffold what is missing

Never overwrite. Each file starts as small as the conventions allow:

- `docs/roadmap.md` in the shape of `loop-doc roadmap`, only if the stakeholder wants milestones.
- `CONTEXT.md` with a "Language" section and an empty translation table, if the repo has a
  domain. `/domain-modeling` fills it later.
- `docs/adr/README.md` — the ADR house format, in the stakeholder's language. Ask whether
  existing ADRs predate it; the first number the rules apply to goes into
  `.claude/ouroboros.json`.
- `docs/code-principles.md` — a header saying the Architect owns it and every rule carries its
  violation as evidence. No rules yet: a rule comes in with its first violation.
- Labels per `loop-doc triage-labels`, created with `gh label create`.
- `.claude/settings.json`: the plugin enabled, so a new machine offers to install it —
  `extraKnownMarketplaces` with `{"ouroboros": {"source": {"source": "github", "repo":
  "Sorong/ouroboros"}, "autoUpdate": true}}` and `enabledPlugins` with
  `"ouroboros@ouroboros": true`.

## 5. Hand back

One PR (`docs/ouroboros`) with everything above. The stakeholder's merge is the gate. From
the next session start on, the repo is registered, and `agent-usage` measures it with all the
others.
