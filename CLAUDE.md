# ouroboros

Das Quell-Repo des Plugins. Sessions hier sind Sessions des Agent-Designers
(`skills/agent-designer/SKILL.md`): Rollen ändern sich nur auf gemessene Muster hin, die
`agent-usage --full` über alle gebundenen Repos zeigt, und nur per PR, den der Stakeholder merged.

- Der Merge auf `main` ist der Release auf jedes Gerät. Vor jedem PR: `python3 scripts/selfcheck.py`.
- Projektspezifisches gehört nie hierher, sondern in die CLAUDE.md des Projekts — und
  Persönliches nie, denn dieses Repo ist öffentlich.
- Die Skripte müssen in jedem Repo still bleiben, in dem der Loop nicht läuft, und dürfen nie
  eine Session abbrechen.
