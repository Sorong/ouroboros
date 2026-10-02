#!/usr/bin/env python3
"""Checks ADRs and CONTEXT.md against their house style.

The rules live in `loop-doc house-style` and in the repo's ADR format (docs/adr/README.md);
here is only what of them can be checked mechanically:

1. **Sentence rule** — one thought per sentence: at most 30 words, at most one dash, no
   semicolon. Applies to CONTEXT.md and to ADRs from `adrProseFrom`.
2. **Terms, not code** — no type, method or field name from this repo. Backticks only for file
   paths and for the fields of the ADR format. Applies to CONTEXT.md outside the translation
   table and to ADRs from `adrProseFrom`.
3. **ADR format** — frontmatter with a valid `status`, references as fields of their own and in
   both directions (all ADRs), the sections in their order (from `adrSectionsFrom`).

The thresholds and the foreign vocabulary are set per repo in `.claude/ouroboros.json`, section
`docstyle` (see `loop-doc house-style`). Only a repo that carries the loop itself, i.e. has
`.claude/ouroboros.json`, is checked — foreign docs are not ours.

`roadmap-status.py` borrows `identifiers_in` and `sentences_in` for the roadmap, so the same
rule is written only once.

No finding: no output, exit 0 — so it stays out of the way as a SessionStart hook.
With findings: report on stdout, exit 1.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import loopcfg

# --- Sentence rule ---------------------------------------------------------------------

MAX_WORDS = 30
MAX_DASHES = 1

# A sentence ends at . ! ?, even if a quotation mark or a parenthesis still closes after it.
# Abbreviations like "e.g." or "z.B." end no sentence. Docs may be written in English or German.
SENTENCE_END = re.compile(r'(?<=[.!?])[)"“”»*_]*\s+')
ABBREVIATIONS = {"e.g.", "i.e.", "cf.", "vs.", "approx.", "No.",
                 "z.B.", "bzw.", "u.a.", "vgl.", "ca.", "d.h.", "ggf.", "evtl.", "usw.",
                 "inkl.", "sog.", "z.T.", "Nr.", "S."}
# Dash: the em dash, or an en dash with spaces around it.
DASH = re.compile(r"—| – ")

MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
EMPHASIS = re.compile(r"(\*\*|\*|__|_)(?=\S)|(?<=\S)(\*\*|\*|__|_)")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def prose_paragraphs(text):
    """[(first line number, paragraph text)] — the prose of a Markdown file. Headings, tables,
    code blocks and the frontmatter are not prose; a list item is a paragraph of its own."""
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
    # A roadmap step's tick is not a word.
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
    """[(line number, sentence, violation)] — sentences that break the sentence rule. The line
    is that of the paragraph the sentence starts in."""
    found = []
    for number, paragraph in prose_paragraphs(text):
        for sentence in split_sentences(plain_text(paragraph)):
            words = len(sentence.split())
            dashes = len(DASH.findall(sentence))
            reasons = []
            if words > MAX_WORDS:
                reasons.append(f"{words} words")
            if dashes > MAX_DASHES:
                reasons.append(f"{dashes} dashes")
            if ";" in sentence:
                reasons.append("semicolon")
            if reasons:
                found.append((number, sentence, ", ".join(reasons)))
    return found


# --- Terms, not code -------------------------------------------------------------------

# Two forms, because they show up differently: what stands in backticks, and what is code
# through CamelCase even without backticks.
BACKTICKED = re.compile(r"`([^`]+)`")
CAMEL_CASE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]*)+\b")
# Allowed in backticks: references to files and directories — traceable, unlike a type name
# that a rename silently invalidates.
PATH_LIKE = re.compile(r"^[\w.-]+(?:/[\w.-]*)+$|^[\w-]+\.(?:md|py|sh|unity|json)$")
# Foreign vocabulary a text may name: technology from outside this repo that no rename here
# touches, and abbreviations that only look like CamelCase. A repo's own type names don't
# belong on this list.
FOREIGN_NAMES = {"PvP", "PoC"}  # the rest per repo: `foreignNames` in the configuration
# The fields and values of the ADR format may stand in backticks (docs/adr/README.md).
ADR_FORMAT_TOKENS = {"status", "accepted", "superseded", "deprecated",
                     "supersedes", "superseded-by", "amends", "amended-by"}


def identifiers_in(line, allowed=frozenset()):
    """The code identifiers of a line, in order and without duplicates."""
    hits = [token for token in BACKTICKED.findall(line)
            if PATH_LIKE.match(token) is None and token not in allowed]
    hits += [token for token in CAMEL_CASE.findall(BACKTICKED.sub("", line))
             if token not in FOREIGN_NAMES]
    return list(dict.fromkeys(hits))


def identifier_lines(text, allowed=frozenset(), skip_tables=False):
    """[(line number, identifier)] across a file. Code blocks don't count; the translation
    table in CONTEXT.md is the one place where code may stand."""
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


# --- ADR format ------------------------------------------------------------------------

SECTIONS_FROM = 1    # from here the layout with sections applies; per repo `adrSectionsFrom`
PROSE_FROM = 1       # from here sentence rule and terms-not-code apply; per repo `adrProseFrom`

STATUS_VALUES = {"accepted", "superseded", "deprecated"}
REFERENCE_FIELDS = {"supersedes": "superseded-by", "superseded-by": "supersedes",
                    "amends": "amended-by", "amended-by": "amends"}
SECTIONS = ["Context", "Options", "Decision", "Consequences"]  # per repo `adrSections`

ADR_FILE = re.compile(r"^(\d{4})-.+\.md$")
ADR_REF = re.compile(r"^ADR-(\d{4})$")
FIELD = re.compile(r"^([a-z-]+):\s*(.*?)\s*$")


def parse_frontmatter(text):
    """({field: value}, errors) — None as fields if the file has no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, []
    fields, errors = {}, []
    for line in lines[1:]:
        if line.strip() == "---":
            return fields, errors
        match = FIELD.match(line)
        if match is None:
            errors.append(f"line \"{line.strip()}\" is not a field")
            continue
        fields[match.group(1)] = match.group(2)
    return fields, errors + ["frontmatter is not closed"]


def references(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def check_adrs(adr_dir):
    """[(file, line|None, finding)] across docs/adr/."""
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
            findings.append((label, None, "no frontmatter"))
        else:
            findings += [(label, None, error) for error in errors]
            status = fields.get("status")
            if status is None:
                findings.append((label, None, "field `status` is missing"))
            elif status not in STATUS_VALUES:
                findings.append((label, None, "`status` is not an allowed value"))
            for field, value in fields.items():
                if field == "status":
                    continue
                if field not in REFERENCE_FIELDS:
                    findings.append((label, None, f"the format has no field `{field}`"))
                    continue
                for ref in references(value):
                    ref_match = ADR_REF.match(ref)
                    if ref_match is None:
                        findings.append((label, None, f"`{field}: {ref}` is not ADR-NNNN"))
                    elif int(ref_match.group(1)) not in adrs:
                        findings.append((label, None, f"`{field}: {ref}` does not exist"))
            if (status == "superseded") != ("superseded-by" in fields):
                findings.append((label, None,
                                 "`superseded` and `superseded-by` go together"))

        if number >= SECTIONS_FROM:
            headings = [line[3:].strip() for line in text.splitlines()
                        if line.startswith("## ")]
            if headings != SECTIONS:
                findings.append((label, None,
                                 f"sections are {headings}, expected {SECTIONS}"))

        if number >= PROSE_FROM:
            for line, sentence, reason in sentences_in(text):
                findings.append((label, line, f"{reason}: \"{shorten(sentence)}\""))
            for line, token in identifier_lines(text, allowed=ADR_FORMAT_TOKENS):
                findings.append((label, line, f"names `{token}`, terms not code"))

    # References in both directions
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
                                     f"`{field}: {ref}`, but {ref} has no "
                                     f"`{inverse}: ADR-{number:04d}`"))
    return findings


def check_context(path):
    findings = []
    text = path.read_text(encoding="utf-8")
    for line, sentence, reason in sentences_in(text):
        findings.append((path.name, line, f"{reason}: \"{shorten(sentence)}\""))
    for line, token in identifier_lines(text, skip_tables=True):
        findings.append((path.name, line, f"names `{token}`, code belongs only in the table"))
    return findings


def shorten(sentence, width=60):
    return sentence if len(sentence) <= width else sentence[:width - 1] + "…"


def configure(root):
    """Takes over the repo's settings. The module constants are the default."""
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
    """Readable when called by hand. As a hook only one line per file or per finding, so the
    report does not fill the session context."""
    lines = ["House style is off (loop-doc house-style, docs/adr/README.md):"]
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
        lines.append(f"  - {label}: {len(numbers)} findings, lines {shown}{more}")
    lines.append("  Details: docstyle")
    return "\n".join(lines)


def adr_name(label):
    match = ADR_FILE.match(label)
    return f"ADR-{match.group(1)}" if match else label


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print a line even without a finding")
    parser.add_argument("--hook", action="store_true",
                        help="output as SessionStart hook JSON instead of text, always exit 0 - "
                             "the finding belongs in the session context, it must not abort a "
                             "session.")
    args = parser.parse_args()

    try:
        root = loopcfg.project_root()
        findings = check(root) if loopcfg.carries_loop(root) else []
    except OSError as error:
        print(f"docstyle: skipped ({error})", file=sys.stderr)
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
            print("House style holds.")

        return 0

    print(report(findings, compact=False))
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
