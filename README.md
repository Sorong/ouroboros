# Ouroboros

Ein Claude-Code-Plugin für einen rollenbasierten Delivery-Loop, der sich selbst verbessert — wie
die Schlange, die sich in den Schwanz beißt: Project Manager, Architect,
Product Owner, Developer, Reviewer, Triage und Agent-Designer. Für Repos mit Roadmap, mit
Issues oder mit Aufträgen aus dem Chat — und für fremde Repos, die unberührt bleiben sollen.

## Aufteilung

Es gibt nur zwei Orte:

- **Das Plugin** (dieses Repo): Rollen, Loop-Vertrag mit Triggern, Konventionen, Prüfungen.
  Gleich für jedes Repo.
- **Das Projekt selbst**: was es über sich weiß — Testbefehl, Sprache, Fallen — steht in seiner
  eigenen CLAUDE.md und Doku, wie ohne Plugin auch.

Dazu merkt sich das Plugin deine Antworten: Code geht immer, alles andere — Push, PR, Issues,
Labels, ADRs, … — fragt es einmal pro Repo und schreibt die Antwort nach `.git/ouroboros.json`
im Clone. Git versioniert dort nichts, ein fremdes Repo bleibt unberührt. Ein eigenes Repo kann
alles auf einmal erlauben, in `.claude/ouroboros.json`. Siehe `docs/permissions.md`.

## Einrichten, einmal pro Gerät

```bash
claude plugin marketplace add Sorong/ouroboros
claude plugin install ouroboros@ouroboros
```

Dann in `~/.claude/settings.json` beim Marktplatz `"autoUpdate": true`. Ab da kommt jeder Commit
auf `main` beim nächsten Sessionstart auf das Gerät (`/reload-plugins` übernimmt ihn sofort).
Ein Repo, das das Plugin in seiner `.claude/settings.json` einschaltet (wie TD), bietet es auf
einem neuen Gerät von selbst zur Installation an.

## Ändern

Die Rollen ändert der Agent-Designer, in einer Session in diesem Repo („weiter mit Agents"), auf
gemessene Muster hin und per PR. Der Merge auf `main` ist der Release — das Manifest führt keine
`version`, Claude Code nimmt den Commit. Vorher läuft `scripts/selfcheck.py`, in der CI noch einmal.

## Messung über alle Repos

`agent-usage` liest die Transkripte jedes Repos im Register (`~/.claude/ouroboros/projects.json`,
je Gerät) und die Zuordnungen aus PR-Antworten und aus `loop-note`.
Sperrfristen und Muster zählen über alle Repos, denn die Definition ist dieselbe. Die
Änderungszeitpunkte der Rollen kommen aus der Git-Geschichte dieses Repos, ohne lokalen Clone
über die GitHub-API.
