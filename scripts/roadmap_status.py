#!/usr/bin/env python3
"""Prüft, ob der dokumentierte Roadmap-Stand zu dem passt, was auf main liegt.

Sechs Prüfungen:

1. **Nachtrag fällig** — Schritte, deren Commits auf `main` liegen (Betreff-Präfix
   `M<N>.<k>`), die in `docs/roadmap/m<N>.md` aber kein Häkchen haben.
2. **Zähler-Drift** — die abgeleiteten Anzeigen in `docs/roadmap.md` (`offen (k/n)`) und
   `README.md` (Fortschrittsbalken + `k/n Schritte`) gegen die Häkchen, die die Quelle sind.
3. **Stale Zeiger** — "Nächster konkreter Schritt" in `docs/roadmap.md`, obwohl der Schritt
   bereits abgehakt ist oder Commits auf `main` hat.
4. **Wiedervorlage fällig** — offene Issues mit `revisit:m<N>`/`revisit:m<N>.<k>`, deren
   Auslösepunkt die Roadmap inzwischen erreicht hat (siehe `loop-doc triage-labels`).
   Braucht `gh` und Netz; ohne beides entfällt still nur diese Prüfung.
5. **Code-Bezeichner** — Typ- und Methodennamen in den Roadmap-Dateien. Die Roadmap nennt
   Entscheidungen, keinen Code (siehe `loop-doc house-style`). Die Regel selbst
   steht in docstyle.py, das sie auch für ADRs und CONTEXT.md prüft.
6. **Satzregel** — ein Gedanke pro Satz in den Roadmap-Dateien: höchstens 30 Wörter, höchstens
   ein Gedankenstrich, kein Semikolon (siehe `loop-doc house-style`). Der Prüfer ist
   derselbe wie für ADRs und CONTEXT.md und steht in docstyle.py.

Die Form, die gelesen wird, beschreibt `loop-doc roadmap`. Geprüft wird nur ein Repo, das den
Loop selbst trägt (`.claude/ouroboros.json`) und eine docs/roadmap.md hat.

Ohne Befund: keine Ausgabe, Exit 0 — damit es als SessionStart-Hook nicht stört.
Mit Befund: Bericht auf stdout, Exit 1.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import docstyle
import loopcfg
from docstyle import identifiers_in, sentences_in, shorten

BAR_FULL = "█"
BAR_EMPTY = "░"

# Commit-Konvention: "M2.3 Text". Siehe `loop-doc git`.
COMMIT_STEP = re.compile(r"^M(\d+)\.(\d+)\b")
# Alt-Bestand vor der Konvention: "Text (#51)" -> Issue-Titel "... (M2 Schritt 3)".
COMMIT_ISSUE = re.compile(r"\(#(\d+)\)")
ISSUE_STEP = re.compile(r"\bM(\d+)\s+Schritt\s+(\d+)\b")

STEP_LINE = re.compile(r"^(\d+)\.\s+(✅\s*)?(.*)$")
OVERVIEW_ROW = re.compile(r"^\|\s*M(\d+)\s*\|")
NEXT_STEP = re.compile(r"\bM(\d+)\s+Schritt\s+(\d+)\b")
COUNTER = re.compile(r"(\d+)\s*/\s*(\d+)")
# Wiedervorlage-Konvention: "revisit:m5", "revisit:m2.6". Siehe `loop-doc triage-labels`.
REVISIT_LABEL = re.compile(r"^revisit:m(\d+)(?:\.(\d+))?$")


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} -> {result.stderr.strip()}")
    return result.stdout


def commit_subjects(root, ref):
    """Betreffzeilen von <ref>. Bewusst nicht HEAD: eine Developer-Session sitzt auf einem
    Feature-Branch, dessen Commits noch nicht gemergt sind."""
    return run(["git", "log", "--format=%s", ref], cwd=root).splitlines()


def steps_on_ref(subjects, issue_titles=None):
    """{Meilenstein: {Schritt, ...}} aus den Commit-Betreffs."""
    found = {}
    for subject in subjects:
        match = COMMIT_STEP.match(subject)
        if match is None and issue_titles is not None:
            issue = COMMIT_ISSUE.search(subject)
            if issue is not None:
                match = ISSUE_STEP.search(issue_titles.get(int(issue.group(1)), ""))
        if match is not None:
            found.setdefault(int(match.group(1)), set()).add(int(match.group(2)))
    return found


def issue_titles(root):
    """Alt-Bestand: Schrittnummern aus Issue-Titeln, für Commits ohne Präfix. Braucht Netz."""
    raw = run(["gh", "issue", "list", "--state", "all", "--limit", "300",
               "--json", "number,title"], cwd=root)
    return {entry["number"]: entry["title"] for entry in json.loads(raw)}


def parse_steps(path):
    """[(Nummer, abgehakt)] aus docs/roadmap/m<N>.md."""
    steps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = STEP_LINE.match(line)
        if match is not None:
            steps.append((int(match.group(1)), match.group(2) is not None))
    return steps


def parse_table(path, status_column):
    """{Meilenstein: Statuszelle} aus einer Markdown-Tabelle mit M<N>-Zeilen."""
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if OVERVIEW_ROW.match(line) is None:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) > status_column:
            rows[int(OVERVIEW_ROW.match(line).group(1))] = cells[status_column]
    return rows


def parse_next_step(path):
    text = path.read_text(encoding="utf-8")
    _, _, tail = text.partition("## Nächster konkreter Schritt")
    match = NEXT_STEP.search(tail)
    return (int(match.group(1)), int(match.group(2))) if match else None


def parked_issues(root):
    """[(Nummer, Titel, [(Meilenstein, Schritt|None), ...])] offener Issues mit revisit-Label."""
    raw = run(["gh", "issue", "list", "--state", "open", "--limit", "300",
               "--json", "number,title,labels"], cwd=root)
    parked = []
    for entry in json.loads(raw):
        triggers = []
        for label in entry["labels"]:
            match = REVISIT_LABEL.match(label["name"])
            if match is not None:
                step = match.group(2)
                triggers.append((int(match.group(1)), int(step) if step else None))
        if triggers:
            parked.append((entry["number"], entry["title"], triggers))
    return parked


def current_position(overview, steps):
    """(Meilenstein, nächster Schritt) — erster Meilenstein der Übersicht ohne Häkchen, und
    darin der erste Schritt ohne Häkchen. Schritt ist None, wenn es für den Meilenstein noch
    keine Schrittdatei gibt (Grobplan)."""
    open_milestones = [n for n, cell in sorted(overview.items()) if "✅" not in cell]
    if not open_milestones:
        return None, None
    milestone = open_milestones[0]
    pending = [num for num, ok in steps.get(milestone, []) if not ok]
    return milestone, (pending[0] if pending else None)


def revisit_due(trigger, position):
    """Ist der Auslösepunkt erreicht? Ein Meilenstein-Auslöser wird mit dem Meilenstein fällig,
    ein Schritt-Auslöser, sobald sein Schritt der nächste ist."""
    milestone, step = trigger
    current_milestone, next_step = position
    if current_milestone is None:
        return True  # kein offener Meilenstein mehr: jeder Auslösepunkt liegt in der Vergangenheit.
    if milestone != current_milestone:
        return milestone < current_milestone
    if step is None:
        return True
    return next_step is not None and step <= next_step


def expected_bar(done, total, width):
    filled = round(done / total * width) if total else 0
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def roadmap_files(root):
    """[(Anzeigename, Text)] — die Dateien, die Entscheidungen tragen sollen."""
    paths = [root / "docs" / "roadmap.md"]
    paths += sorted((root / "docs" / "roadmap").glob("m*.md"))
    return [(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
            for path in paths]


def code_identifiers(root):
    """[(Datei, Zeilennummer, Bezeichner)] — Code in den Roadmap-Dateien."""
    found = []
    for label, text in roadmap_files(root):
        for number, line in enumerate(text.splitlines(), start=1):
            found += [(label, number, token) for token in identifiers_in(line)]
    return found


def long_sentences(root):
    """[(Datei, Zeilennummer, Satz, Verstoß)] — Sätze der Roadmap-Dateien gegen die Satzregel."""
    found = []
    for label, text in roadmap_files(root):
        found += [(label, number, sentence, reason)
                  for number, sentence, reason in sentences_in(text)]
    return found


def check(root, ref, via_issues):
    if not loopcfg.carries_loop(root) or not (root / "docs" / "roadmap.md").is_file():
        return [], []
    docstyle.configure(root)
    findings = []
    step_files = {int(p.stem[1:]): p for p in sorted((root / "docs" / "roadmap").glob("m*.md"))}
    steps = {n: parse_steps(p) for n, p in step_files.items()}
    done = {n: {num for num, ok in s if ok} for n, s in steps.items()}

    titles = issue_titles(root) if via_issues else None
    on_ref = steps_on_ref(commit_subjects(root, ref), titles)

    # 1. Nachtrag fällig
    for milestone in sorted(on_ref):
        pending = sorted(on_ref[milestone] - done.get(milestone, set()))
        for step in pending:
            findings.append(
                f"Nachtrag fällig: M{milestone}.{step} liegt auf {ref}, "
                f"aber docs/roadmap/m{milestone}.md hat dort kein Häkchen."
            )

    # 2. Zähler-Drift gegen die Häkchen
    overview = parse_table(root / "docs" / "roadmap.md", 4)
    readme = parse_table(root / "README.md", 3) if (root / "README.md").is_file() else {}
    for milestone, entries in sorted(steps.items()):
        total, complete = len(entries), len(done[milestone])
        for label, cell in (("docs/roadmap.md", overview.get(milestone)),
                            ("README.md", readme.get(milestone))):
            if cell is None:
                continue
            counter = COUNTER.search(cell)
            if counter is None:
                if complete != total and "✅" in cell:
                    findings.append(
                        f"Zähler-Drift: {label} meldet M{milestone} als erledigt, "
                        f"docs/roadmap/m{milestone}.md hat aber nur {complete}/{total} Häkchen."
                    )
                continue
            shown = (int(counter.group(1)), int(counter.group(2)))
            if shown != (complete, total):
                findings.append(
                    f"Zähler-Drift: {label} zeigt M{milestone} als {shown[0]}/{shown[1]}, "
                    f"docs/roadmap/m{milestone}.md hat {complete}/{total} Häkchen."
                )
            bar = re.search(f"[{BAR_FULL}{BAR_EMPTY}]+", cell)
            if bar is not None:
                want = expected_bar(complete, total, len(bar.group(0)))
                if bar.group(0) != want:
                    findings.append(
                        f"Balken-Drift: {label} zeigt M{milestone} als "
                        f"`{bar.group(0)}`, richtig wäre `{want}`."
                    )

    # 3. Stale Zeiger
    pointer = parse_next_step(root / "docs" / "roadmap.md")
    if pointer is not None:
        milestone, step = pointer
        if step in done.get(milestone, set()) or step in on_ref.get(milestone, set()):
            findings.append(
                f"Stale Zeiger: docs/roadmap.md nennt M{milestone} Schritt {step} als "
                f"nächsten Schritt, der ist aber schon erledigt."
            )

    # 5. Code-Bezeichner
    for label, number, token in code_identifiers(root):
        findings.append(
            f"Code-Bezeichner: {label}:{number} nennt `{token}`. Die Roadmap verweist auf ADRs "
            f"und benutzt CONTEXT.md-Begriffe, siehe loop-doc house-style."
        )

    # 6. Satzregel
    for label, number, sentence, reason in long_sentences(root):
        findings.append(
            f"Satzregel: {label}:{number} {reason}: „{shorten(sentence)}\". Ein Gedanke pro "
            f"Satz, siehe loop-doc house-style."
        )

    # 4. Wiedervorlage fällig
    revisits = []
    position = current_position(overview, steps)
    try:
        parked = parked_issues(root)
    except (RuntimeError, OSError):
        parked = []  # ohne gh/Netz entfällt nur diese Prüfung, nicht der ganze Bericht.
    for number, title, triggers in parked:
        due = [t for t in triggers if revisit_due(t, position)]
        if not due:
            continue
        milestone, step = min(due, key=lambda t: (t[0], -1 if t[1] is None else t[1]))
        at = f"M{milestone}" if step is None else f"M{milestone} Schritt {step}"
        revisits.append(f"#{number} wollte bei {at} nochmal angesehen werden: {title}")

    return findings, revisits


def report(findings, revisits):
    lines = []
    if findings:
        lines.append("Roadmap-Stand weicht ab:")
        lines += [f"  - {f}" for f in findings]
        lines.append("  Nachtragen per Abschluss-Konvention: \"abschluss M<N>.<k>\" "
                     "(ouroboros:product-owner).")
    if revisits:
        lines.append("Wiedervorlage fällig:")
        lines += [f"  - {r}" for r in revisits]
        lines.append("  Erneut triagieren (ouroboros:triage) — das Urteil liegt beim "
                     "Stakeholder, nicht bei der Session.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="main",
                        help="Referenz, die den gemergten Stand trägt (Default: main)")
    parser.add_argument("--via-issues", action="store_true",
                        help="Alt-Commits ohne M<N>.<k>-Präfix über ihre (#n)-Referenz und den "
                             "Issue-Titel auflösen. Braucht gh und Netz.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="auch bei sauberem Stand eine Zeile ausgeben")
    parser.add_argument("--hook", action="store_true",
                        help="Ausgabe als SessionStart-Hook-JSON statt als Text, immer Exit 0 - "
                             "der Befund gehört in den Session-Kontext, er soll keine Session "
                             "abbrechen.")
    args = parser.parse_args()

    try:
        root = loopcfg.project_root()
        findings, revisits = check(root, args.ref, args.via_issues)
    except (RuntimeError, OSError) as error:
        # Als SessionStart-Hook darf das nie eine Session blockieren.
        print(f"roadmap-status: übersprungen ({error})", file=sys.stderr)
        return 0

    if args.hook:
        if findings or revisits:
            message = report(findings, revisits)
            print(json.dumps({"systemMessage": message,
                              "hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": message}}))
        return 0

    if not findings and not revisits:
        if args.verbose:
            print("Roadmap-Stand ist konsistent, keine Wiedervorlage fällig.")
        return 0

    print(report(findings, revisits))
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
