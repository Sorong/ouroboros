# ouroboros

The plugin's source repo. Sessions here are sessions of the Agent-Designer
(`skills/agent-designer/SKILL.md`): roles change only on measured patterns that
`agent-usage --full` shows across all bound repos, and only by a PR the stakeholder merges.

- The merge to `main` is the release to every machine. Before every PR: `python3 scripts/selfcheck.py`.
- Nothing project-specific belongs here — it goes in the project's own CLAUDE.md. Nothing
  personal either, and no references to other projects, because this repo is public.
- The scripts must stay silent in every repo where the loop doesn't run, and must never abort a
  session.
- Trigger phrases and attribution places come in English and German. Parsers accept both forms;
  never drop the German ones, since existing repos and PR history use them.
