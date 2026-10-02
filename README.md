# Ouroboros

A Claude Code plugin for a role-based delivery loop that improves itself — like the snake biting
its own tail: Project Manager, Architect, Product Owner, Developer, Reviewer, Triage and
Agent-Designer. For repos with a roadmap, with issues, or with orders from the chat — and for
someone else's repos that are to stay untouched.

## Split

There are only two places:

- **The plugin** (this repo): roles, the loop contract with its triggers, conventions, checks.
  The same for every repo.
- **The project itself**: what it knows about itself — test command, language, pitfalls — lives
  in its own CLAUDE.md and docs, as it would without the plugin.

On top of that the plugin remembers your answers: code is always fine, everything else — push,
PR, issues, labels, ADRs, … — it asks once per repo and writes the answer to
`.git/ouroboros.json` in the clone. Git versions nothing there, so a foreign repo stays
untouched. A repo of your own can allow everything at once, in `.claude/ouroboros.json`. See
`docs/permissions.md`.

## Triggers

You start a role by naming a unit, in English or German: "continue with M2" / "weiter mit M2",
"cut M2.3" / "schnitt M2.3", "order: …" / "auftrag: …", and so on. The full list is in
`docs/loop.md`.

## Install, once per machine

```bash
claude plugin marketplace add Sorong/ouroboros
claude plugin install ouroboros@ouroboros
```

Then set `"autoUpdate": true` for the marketplace in `~/.claude/settings.json`. From then on
every commit on `main` reaches the machine at the next session start (`/reload-plugins` picks it
up immediately). A repo that enables the plugin in its `.claude/settings.json` offers it for
installation on a new machine by itself.

## Changing it

The Agent-Designer changes the roles, in a session in this repo ("continue with agents"), on
measured patterns and by PR. The merge to `main` is the release — the manifest has no
`version`, Claude Code takes the commit. `scripts/selfcheck.py` runs before that, and once more
in CI.

## Measuring across all repos

`agent-usage` reads the transcripts of every repo in the registry
(`~/.claude/ouroboros/projects.json`, per machine) and the attributions from PR replies and from
`loop-note`. Lock periods and patterns count across all repos, because the definition is the
same. The roles' change times come from this repo's Git history, or via the GitHub API when
there is no local clone.

## License

[MIT](LICENSE)
