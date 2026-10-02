#!/usr/bin/env python3
"""Checks whether the documented roadmap state fits what is on main.

Six checks:

1. **Close-out due** — steps whose commits are on `main` (subject prefix `M<N>.<k>`) but
   that have no tick in `docs/roadmap/m<N>.md`.
2. **Counter drift** — the derived displays in `docs/roadmap.md` (`open (k/n)`) and
   `README.md` (progress bar + `k/n steps`) against the ticks, which are the source.
3. **Stale pointer** — the "next concrete step" in `docs/roadmap.md` although that step is
   already ticked or has commits on `main`.
4. **Revisit due** — open issues with `revisit:m<N>`/`revisit:m<N>.<k>` whose trigger point the
   roadmap has reached by now (see `loop-doc triage-labels`). Needs `gh` and a network;
   without both, only this check drops out, silently.
5. **Code identifiers** — type and method names in the roadmap files. The roadmap names
   decisions, not code (see `loop-doc house-style`). The rule itself lives in docstyle.py,
   which also checks it for ADRs and CONTEXT.md.
6. **Sentence rule** — one thought per sentence in the roadmap files: at most 30 words, at most
   one dash, no semicolon (see `loop-doc house-style`). The checker is the same as for ADRs and
   CONTEXT.md and lives in docstyle.py.

The shape that is read is described in `loop-doc roadmap`, in English or German wording. Only a
repo that carries the loop itself (`.claude/ouroboros.json`) and has a docs/roadmap.md is
checked.

No finding: no output, exit 0 — so it stays out of the way as a SessionStart hook.
With findings: report on stdout, exit 1.
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

# Commit convention: "M2.3 Text". See `loop-doc git`.
COMMIT_STEP = re.compile(r"^M(\d+)\.(\d+)\b")
# A step named in prose: "M2 step 3", or the German "M2 Schritt 3".
NAMED_STEP = re.compile(r"\bM(\d+)\s+(?:step|Schritt)\s+(\d+)\b", re.IGNORECASE)
# Legacy commits from before the convention: "Text (#51)" -> issue title "... (M2 step 3)".
COMMIT_ISSUE = re.compile(r"\(#(\d+)\)")
ISSUE_STEP = NAMED_STEP

STEP_LINE = re.compile(r"^(\d+)\.\s+(✅\s*)?(.*)$")
OVERVIEW_ROW = re.compile(r"^\|\s*M(\d+)\s*\|")
NEXT_STEP = NAMED_STEP
# The section that names the next step, in English or German.
NEXT_STEP_HEADING = re.compile(
    r"^##\s+(?:Next concrete step|Nächster konkreter Schritt)\s*$", re.IGNORECASE | re.MULTILINE)
COUNTER = re.compile(r"(\d+)\s*/\s*(\d+)")
# Revisit convention: "revisit:m5", "revisit:m2.6". See `loop-doc triage-labels`.
REVISIT_LABEL = re.compile(r"^revisit:m(\d+)(?:\.(\d+))?$")


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} -> {result.stderr.strip()}")
    return result.stdout


def commit_subjects(root, ref):
    """The subject lines of <ref>. Deliberately not HEAD: a Developer session sits on a feature
    branch whose commits are not merged yet."""
    return run(["git", "log", "--format=%s", ref], cwd=root).splitlines()


def steps_on_ref(subjects, issue_titles=None):
    """{milestone: {step, ...}} from the commit subjects."""
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
    """Legacy: step numbers from issue titles, for commits without a prefix. Needs a network."""
    raw = run(["gh", "issue", "list", "--state", "all", "--limit", "300",
               "--json", "number,title"], cwd=root)
    return {entry["number"]: entry["title"] for entry in json.loads(raw)}


def parse_steps(path):
    """[(number, ticked)] from docs/roadmap/m<N>.md."""
    steps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = STEP_LINE.match(line)
        if match is not None:
            steps.append((int(match.group(1)), match.group(2) is not None))
    return steps


def parse_table(path, status_column):
    """{milestone: status cell} from a Markdown table with M<N> rows."""
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
    heading = NEXT_STEP_HEADING.search(text)
    if heading is None:
        return None
    match = NEXT_STEP.search(text, heading.end())
    return (int(match.group(1)), int(match.group(2))) if match else None


def parked_issues(root):
    """[(number, title, [(milestone, step|None), ...])] of open issues with a revisit label."""
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
    """(milestone, next step) — the overview's first milestone without a tick, and in it the
    first step without a tick. The step is None if the milestone has no step file yet (rough
    plan)."""
    open_milestones = [n for n, cell in sorted(overview.items()) if "✅" not in cell]
    if not open_milestones:
        return None, None
    milestone = open_milestones[0]
    pending = [num for num, ok in steps.get(milestone, []) if not ok]
    return milestone, (pending[0] if pending else None)


def revisit_due(trigger, position):
    """Has the trigger point been reached? A milestone trigger falls due with the milestone, a
    step trigger as soon as its step is the next one."""
    milestone, step = trigger
    current_milestone, next_step = position
    if current_milestone is None:
        return True  # no open milestone left: every trigger point lies in the past.
    if milestone != current_milestone:
        return milestone < current_milestone
    if step is None:
        return True
    return next_step is not None and step <= next_step


def expected_bar(done, total, width):
    filled = round(done / total * width) if total else 0
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def roadmap_files(root):
    """[(display name, text)] — the files that are meant to carry decisions."""
    paths = [root / "docs" / "roadmap.md"]
    paths += sorted((root / "docs" / "roadmap").glob("m*.md"))
    return [(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
            for path in paths]


def code_identifiers(root):
    """[(file, line number, identifier)] — code in the roadmap files."""
    found = []
    for label, text in roadmap_files(root):
        for number, line in enumerate(text.splitlines(), start=1):
            found += [(label, number, token) for token in identifiers_in(line)]
    return found


def long_sentences(root):
    """[(file, line number, sentence, violation)] — roadmap sentences against the sentence rule."""
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

    # 1. Close-out due
    for milestone in sorted(on_ref):
        pending = sorted(on_ref[milestone] - done.get(milestone, set()))
        for step in pending:
            findings.append(
                f"Close-out due: M{milestone}.{step} is on {ref}, "
                f"but docs/roadmap/m{milestone}.md has no tick there."
            )

    # 2. Counter drift against the ticks
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
                        f"Counter drift: {label} reports M{milestone} as done, "
                        f"but docs/roadmap/m{milestone}.md has only {complete}/{total} ticks."
                    )
                continue
            shown = (int(counter.group(1)), int(counter.group(2)))
            if shown != (complete, total):
                findings.append(
                    f"Counter drift: {label} shows M{milestone} as {shown[0]}/{shown[1]}, "
                    f"docs/roadmap/m{milestone}.md has {complete}/{total} ticks."
                )
            bar = re.search(f"[{BAR_FULL}{BAR_EMPTY}]+", cell)
            if bar is not None:
                want = expected_bar(complete, total, len(bar.group(0)))
                if bar.group(0) != want:
                    findings.append(
                        f"Bar drift: {label} shows M{milestone} as "
                        f"`{bar.group(0)}`, it should be `{want}`."
                    )

    # 3. Stale pointer
    pointer = parse_next_step(root / "docs" / "roadmap.md")
    if pointer is not None:
        milestone, step = pointer
        if step in done.get(milestone, set()) or step in on_ref.get(milestone, set()):
            findings.append(
                f"Stale pointer: docs/roadmap.md names M{milestone} step {step} as the "
                f"next step, but it is already done."
            )

    # 5. Code identifiers
    for label, number, token in code_identifiers(root):
        findings.append(
            f"Code identifier: {label}:{number} names `{token}`. The roadmap points at ADRs "
            f"and uses CONTEXT.md terms, see loop-doc house-style."
        )

    # 6. Sentence rule
    for label, number, sentence, reason in long_sentences(root):
        findings.append(
            f"Sentence rule: {label}:{number} {reason}: \"{shorten(sentence)}\". One thought per "
            f"sentence, see loop-doc house-style."
        )

    # 4. Revisit due
    revisits = []
    position = current_position(overview, steps)
    try:
        parked = parked_issues(root)
    except (RuntimeError, OSError):
        parked = []  # without gh/network only this check drops out, not the whole report.
    for number, title, triggers in parked:
        due = [t for t in triggers if revisit_due(t, position)]
        if not due:
            continue
        milestone, step = min(due, key=lambda t: (t[0], -1 if t[1] is None else t[1]))
        at = f"M{milestone}" if step is None else f"M{milestone} step {step}"
        revisits.append(f"#{number} asked to be looked at again at {at}: {title}")

    return findings, revisits


def report(findings, revisits):
    lines = []
    if findings:
        lines.append("Roadmap state is off:")
        lines += [f"  - {f}" for f in findings]
        lines.append("  Catch up via the close-out: \"close out M<N>.<k>\" / \"abschluss "
                     "M<N>.<k>\" (ouroboros:product-owner).")
    if revisits:
        lines.append("Revisit due:")
        lines += [f"  - {r}" for r in revisits]
        lines.append("  Triage again (ouroboros:triage) — the verdict is the stakeholder's, "
                     "not the session's.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="main",
                        help="ref that carries the merged state (default: main)")
    parser.add_argument("--via-issues", action="store_true",
                        help="resolve legacy commits without an M<N>.<k> prefix via their (#n) "
                             "reference and the issue title. Needs gh and a network.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print a line even when the state is clean")
    parser.add_argument("--hook", action="store_true",
                        help="output as SessionStart hook JSON instead of text, always exit 0 - "
                             "the finding belongs in the session context, it must not abort a "
                             "session.")
    args = parser.parse_args()

    try:
        root = loopcfg.project_root()
        findings, revisits = check(root, args.ref, args.via_issues)
    except (RuntimeError, OSError) as error:
        # As a SessionStart hook this must never block a session.
        print(f"roadmap-status: skipped ({error})", file=sys.stderr)
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
            print("Roadmap state is consistent, no revisit due.")

        return 0

    print(report(findings, revisits))
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
