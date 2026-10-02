#!/usr/bin/env python3
"""Prüft ADRs und CONTEXT.md gegen ihren Hausstil.

Die Regeln stehen in `loop-doc house-style` und im ADR-Format des Repos (docs/adr/README.md);
hier steht nur, was davon mechanisch prüfbar ist:

1. **Satzregel** — ein Gedanke pro Satz: höchstens 30 Wörter, höchstens ein Gedankenstrich,
   kein Semikolon. Gilt für CONTEXT.md und für ADRs ab `adrProseFrom`.
2. **Begriffe statt Code** — kein Typ-, Methoden- oder Feldname aus diesem Repo. Backticks
   nur für Dateipfade und für die Felder des ADR-Formats. Gilt für CONTEXT.md außerhalb der
   Übersetzungstabelle und für ADRs ab `adrProseFrom`.
3. **ADR-Format** — Frontmatter mit gültigem `status`, Verweise als eigene Felder und in
   beiden Richtungen (alle ADRs), die Abschnitte in ihrer Reihenfolge (ab `adrSectionsFrom`).

Die Schwellen und das Fremdvokabular stehen je Repo in `.claude/ouroboros.json`, Abschnitt
`docstyle` (siehe `loop-doc house-style`). Geprüft wird nur ein Repo, das den Loop selbst
trägt, also `.claude/ouroboros.json` hat — fremde Doku ist nicht unsere.

`roadmap-status.py` leiht sich `identifiers_in` und `sentences_in` für die Roadmap, damit
dieselbe Regel nur einmal geschrieben ist.

Ohne Befund: keine Ausgabe, Exit 0 — damit es als SessionStart-Hook nicht stört.
Mit Befund: Bericht auf stdout, Exit 1.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import loopcfg

# --- Satzregel -------------------------------------------------------------------------

MAX_WORDS = 30
MAX_DASHES = 1

# Ein Satz endet an . ! ?, auch wenn danach noch ein Anführungszeichen oder eine Klammer
# schließt. Abkürzungen wie „z.B." enden keinen Satz.
SENTENCE_END = re.compile(r'(?<=[.!?])[)"“”»*_]*\s+')
ABBREVIATIONS = {"z.B.", "bzw.", "u.a.", "vgl.", "ca.", "d.h.", "ggf.", "evtl.", "usw.",
                 "inkl.", "sog.", "z.T.", "Nr.", "S."}
# Gedankenstrich: der Geviertstrich, oder ein Halbgeviertstrich mit Leerzeichen um sich.
DASH = re.compile(r"—| – ")

MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
EMPHASIS = re.compile(r"(\*\*|\*|__|_)(?=\S)|(?<=\S)(\*\*|\*|__|_)")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def prose_paragraphs(text):
    """[(erste Zeilennummer, Absatztext)] — Fließtext einer Markdown-Datei. Überschriften,
    Tabellen, Code-Blöcke und das Frontmatter sind kein Fließtext; ein Listenpunkt ist ein
    eigener Absatz."""
    paragraphs = []
    current, start = [], None
    in_fence, in_frontmatter = False, False

    def flush():
        nonlocal current, start
        if current:
            paragraphs.append((start, " ".join(current)))
        current, start = [], None

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if number == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            in_frontmatter = stripped != "---"
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            flush()
            continue
        if in_fence or not stripped or stripped.startswith(("#", "|", "<!--")):
            flush()
            continue
        if LIST_MARKER.match(line):
            flush()
            line = LIST_MARKER.sub("", line, count=1)
        if start is None:
            start = number
        current.append(line.strip())
    flush()
    return paragraphs


def plain_text(paragraph):
    # Das Häkchen eines Roadmap-Schritts ist kein Wort.
    text = MARKDOWN_LINK.sub(r"\1", paragraph).replace("✅", "")
    return EMPHASIS.sub("", text)


def split_sentences(paragraph):
    sentences, buffer = [], ""
    for piece in SENTENCE_END.split(paragraph):
        buffer = f"{buffer} {piece}".strip()
        if not buffer:
            continue
        if buffer.split()[-1].lstrip('(„"') in ABBREVIATIONS:
            continue
        sentences.append(buffer)
        buffer = ""
    if buffer:
        sentences.append(buffer)
    return sentences


def sentences_in(text):
    """[(Zeilennummer, Satz, Verstoß)] — Sätze, die die Satzregel verletzen. Die Zeile ist
    die des Absatzes, in dem der Satz beginnt."""
    found = []
    for number, paragraph in prose_paragraphs(text):
        for sentence in split_sentences(plain_text(paragraph)):
            words = len(sentence.split())
            dashes = len(DASH.findall(sentence))
            reasons = []
            if words > MAX_WORDS:
                reasons.append(f"{words} Wörter")
            if dashes > MAX_DASHES:
                reasons.append(f"{dashes} Gedankenstriche")
            if ";" in sentence:
                reasons.append("Semikolon")
            if reasons:
                found.append((number, sentence, ", ".join(reasons)))
    return found


# --- Begriffe statt Code ---------------------------------------------------------------

# Zwei Formen, weil sie unterschiedlich auffallen: was in Backticks steht, und was durch
# binnengroßes CamelCase auch ohne Backticks Code ist.
BACKTICKED = re.compile(r"`([^`]+)`")
CAMEL_CASE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]*)+\b")
# Erlaubt in Backticks: Verweise auf Dateien und Verzeichnisse — nachverfolgbar, anders als
# ein Typname, den ein Rename still ungültig macht.
PATH_LIKE = re.compile(r"^[\w.-]+(?:/[\w.-]*)+$|^[\w-]+\.(?:md|py|sh|unity|json)$")
# Fremdvokabular, das ein Text benennen darf: Technik von außerhalb dieses Repos, die keinem
# Rename hier unterliegt, und Abkürzungen, die nur wie CamelCase aussehen. Eigene Typnamen
# gehören nicht auf diese Liste.
FOREIGN_NAMES = {"PvP", "PoC"}  # Rest je Repo: `foreignNames` in der Konfiguration
# Die Felder und Werte des ADR-Formats dürfen in Backticks stehen (docs/adr/README.md).
ADR_FORMAT_TOKENS = {"status", "accepted", "superseded", "deprecated",
                     "supersedes", "superseded-by", "amends", "amended-by"}


def identifiers_in(line, allowed=frozenset()):
    """Code-Bezeichner einer Zeile, in Reihenfolge und ohne Doppelte."""
    hits = [token for token in BACKTICKED.findall(line)
            if PATH_LIKE.match(token) is None and token not in allowed]
    hits += [token for token in CAMEL_CASE.findall(BACKTICKED.sub("", line))
             if token not in FOREIGN_NAMES]
    return list(dict.fromkeys(hits))


def identifier_lines(text, allowed=frozenset(), skip_tables=False):
    """[(Zeilennummer, Bezeichner)] über eine Datei. Code-Blöcke zählen nicht; die
    Übersetzungstabelle in CONTEXT.md ist der eine Ort, an dem Code stehen darf."""
    found = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or (skip_tables and line.lstrip().startswith("|")):
            continue
        found += [(number, token) for token in identifiers_in(line, allowed)]
    return found


# --- ADR-Format ------------------------------------------------------------------------

SECTIONS_FROM = 1    # ab hier gilt der Aufbau mit Abschnitten; je Repo `adrSectionsFrom`
PROSE_FROM = 1       # ab hier gelten Satzregel und Begriffe statt Code; je Repo `adrProseFrom`

STATUS_VALUES = {"accepted", "superseded", "deprecated"}
REFERENCE_FIELDS = {"supersedes": "superseded-by", "superseded-by": "supersedes",
                    "amends": "amended-by", "amended-by": "amends"}
SECTIONS = ["Kontext", "Optionen", "Entscheidung", "Konsequenzen"]

ADR_FILE = re.compile(r"^(\d{4})-.+\.md$")
ADR_REF = re.compile(r"^ADR-(\d{4})$")
FIELD = re.compile(r"^([a-z-]+):\s*(.*?)\s*$")


def parse_frontmatter(text):
    """({Feld: Wert}, Fehler) — None als Felder, wenn die Datei kein Frontmatter hat."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, []
    fields, errors = {}, []
    for line in lines[1:]:
        if line.strip() == "---":
            return fields, errors
        match = FIELD.match(line)
        if match is None:
            errors.append(f"Zeile „{line.strip()}\" ist kein Feld")
            continue
        fields[match.group(1)] = match.group(2)
    return fields, errors + ["Frontmatter wird nicht geschlossen"]


def references(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def check_adrs(adr_dir):
    """[(Datei, Zeile|None, Befund)] über docs/adr/."""
    findings = []
    adrs = {}
    for path in sorted(adr_dir.iterdir()):
        match = ADR_FILE.match(path.name)
        if match is not None:
            adrs[int(match.group(1))] = path

    parsed = {}
    for number, path in adrs.items():
        label = path.name
        text = path.read_text(encoding="utf-8")
        fields, errors = parse_frontmatter(text)
        parsed[number] = fields or {}
        if fields is None:
            findings.append((label, None, "kein Frontmatter"))
        else:
            findings += [(label, None, error) for error in errors]
            status = fields.get("status")
            if status is None:
                findings.append((label, None, "Feld `status` fehlt"))
            elif status not in STATUS_VALUES:
                findings.append((label, None, "`status` ist kein erlaubter Wert"))
            for field, value in fields.items():
                if field == "status":
                    continue
                if field not in REFERENCE_FIELDS:
                    findings.append((label, None, f"Feld `{field}` kennt das Format nicht"))
                    continue
                for ref in references(value):
                    ref_match = ADR_REF.match(ref)
                    if ref_match is None:
                        findings.append((label, None, f"`{field}: {ref}` ist kein ADR-NNNN"))
                    elif int(ref_match.group(1)) not in adrs:
                        findings.append((label, None, f"`{field}: {ref}` gibt es nicht"))
            if (status == "superseded") != ("superseded-by" in fields):
                findings.append((label, None,
                                 "`superseded` und `superseded-by` gehören zusammen"))

        if number >= SECTIONS_FROM:
            headings = [line[3:].strip() for line in text.splitlines()
                        if line.startswith("## ")]
            if headings != SECTIONS:
                findings.append((label, None,
                                 f"Abschnitte sind {headings}, erwartet {SECTIONS}"))

        if number >= PROSE_FROM:
            for line, sentence, reason in sentences_in(text):
                findings.append((label, line, f"{reason}: „{shorten(sentence)}\""))
            for line, token in identifier_lines(text, allowed=ADR_FORMAT_TOKENS):
                findings.append((label, line, f"nennt `{token}`, Begriffe statt Code"))

    # Verweise in beiden Richtungen
    for number, fields in parsed.items():
        for field, value in fields.items():
            inverse = REFERENCE_FIELDS.get(field)
            if inverse is None:
                continue
            for ref in references(value):
                ref_match = ADR_REF.match(ref)
                if ref_match is None or int(ref_match.group(1)) not in parsed:
                    continue
                other = parsed[int(ref_match.group(1))]
                if f"ADR-{number:04d}" not in references(other.get(inverse, "")):
                    findings.append((adrs[number].name, None,
                                     f"`{field}: {ref}`, aber {ref} hat kein "
                                     f"`{inverse}: ADR-{number:04d}`"))
    return findings


def check_context(path):
    findings = []
    text = path.read_text(encoding="utf-8")
    for line, sentence, reason in sentences_in(text):
        findings.append((path.name, line, f"{reason}: „{shorten(sentence)}\""))
    for line, token in identifier_lines(text, skip_tables=True):
        findings.append((path.name, line, f"nennt `{token}`, Code steht nur in der Tabelle"))
    return findings


def shorten(sentence, width=60):
    return sentence if len(sentence) <= width else sentence[:width - 1] + "…"


def configure(root):
    """Übernimmt die Einstellungen des Repos. Die Module-Konstanten sind die Vorgabe."""
    global SECTIONS_FROM, PROSE_FROM, SECTIONS, FOREIGN_NAMES
    settings = loopcfg.config(root, "docstyle")
    SECTIONS_FROM = int(settings.get("adrSectionsFrom", SECTIONS_FROM))
    PROSE_FROM = int(settings.get("adrProseFrom", PROSE_FROM))
    SECTIONS = list(settings.get("adrSections", SECTIONS))
    FOREIGN_NAMES = FOREIGN_NAMES | set(settings.get("foreignNames", []))


def check(root):
    configure(root)
    findings = []
    if (root / "docs" / "adr").is_dir():
        findings += check_adrs(root / "docs" / "adr")
    if (root / "CONTEXT.md").is_file():
        findings += check_context(root / "CONTEXT.md")
    return findings


def report(findings, compact):
    """Lesbar für den Aufruf von Hand. Als Hook nur eine Zeile je Datei oder je Befund, damit
    der Bericht den Session-Kontext nicht füllt."""
    lines = ["Hausstil weicht ab (loop-doc house-style, docs/adr/README.md):"]
    if not compact:
        for label, line, finding in findings:
            where = f"{label}:{line}" if line else label
            lines.append(f"  - {where}: {finding}")
        return "\n".join(lines)
    by_finding, by_file = {}, {}
    for label, line, finding in findings:
        if line is None:
            by_finding.setdefault(finding, []).append(label)
        else:
            by_file.setdefault(label, []).append(line)
    for finding, labels in by_finding.items():
        names = ", ".join(dict.fromkeys(adr_name(label) for label in labels))
        lines.append(f"  - {finding}: {names}")
    for label, numbers in by_file.items():
        shown = ", ".join(str(n) for n in sorted(set(numbers))[:12])
        more = " …" if len(set(numbers)) > 12 else ""
        lines.append(f"  - {label}: {len(numbers)} Befunde, Zeilen {shown}{more}")
    lines.append("  Details: docstyle")
    return "\n".join(lines)


def adr_name(label):
    match = ADR_FILE.match(label)
    return f"ADR-{match.group(1)}" if match else label


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="auch ohne Befund eine Zeile ausgeben")
    parser.add_argument("--hook", action="store_true",
                        help="Ausgabe als SessionStart-Hook-JSON statt als Text, immer Exit 0 - "
                             "der Befund gehört in den Session-Kontext, er soll keine Session "
                             "abbrechen.")
    args = parser.parse_args()

    try:
        root = loopcfg.project_root()
        findings = check(root) if loopcfg.carries_loop(root) else []
    except OSError as error:
        print(f"docstyle: übersprungen ({error})", file=sys.stderr)
        return 0

    if args.hook:
        if findings:
            message = report(findings, compact=True)
            print(json.dumps({"systemMessage": message,
                              "hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": message}}))
        return 0

    if not findings:
        if args.verbose:
            print("Hausstil eingehalten.")
        return 0

    print(report(findings, compact=False))
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
