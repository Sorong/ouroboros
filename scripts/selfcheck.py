#!/usr/bin/env python3
"""Prüft das Plugin, bevor es ausgerollt wird — lokal und in der CI.

Jeder Commit auf `main` ist eine neue Version (das Manifest führt keine `version`, Claude Code
nimmt den Commit). Was hier nicht auffällt, landet beim nächsten Sessionstart auf jedem Gerät.

1. Manifeste sind gültiges JSON, das Plugin heißt wie der Marktplatz-Eintrag.
2. Jeder Skill und jeder Agent hat Frontmatter mit `name` und `description`, und das
   Frontmatter ist gültiges YAML — eine Beschreibung mit „: " ohne Anführungszeichen kommt
   sonst leer an.
3. Jedes Skript kompiliert.
4. Jedes `loop-doc <name>` in den Texten gibt es unter `docs/`.
5. Der Hook bleibt in einem Repo ohne Loop still und schreibt gültiges JSON in einem
   Wegwerf-Repo, das den Loop trägt.
"""

import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors = []


def fail(message):
    errors.append(message)


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    return text[4:end] if end > 0 else None


def check_manifests():
    try:
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError) as error:
        fail(f"Manifest: {error}")
        return
    if plugin.get("name") not in {entry.get("name") for entry in market.get("plugins", [])}:
        fail("Manifest: plugin.json-Name fehlt in marketplace.json")
    if "version" in plugin:
        fail("Manifest: plugin.json führt eine version — dann zählt ein Commit nicht als Update")


def check_frontmatter():
    try:
        import yaml
    except ImportError:
        yaml = None
    for path in [*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("agents/*.md")]:
        block = frontmatter(path)
        label = path.relative_to(ROOT).as_posix()
        if block is None:
            fail(f"{label}: kein Frontmatter")
            continue
        if yaml is not None:
            try:
                data = yaml.safe_load(block)
            except yaml.YAMLError as error:
                fail(f"{label}: Frontmatter ist kein YAML ({error})")
                continue
        else:  # ohne PyYAML: die häufigste Falle von Hand prüfen
            data = {}
            for line in block.splitlines():
                key, _, value = line.partition(": ")
                if value and not value.startswith(('"', "'")) and ": " in value:
                    fail(f"{label}: `{key}` enthält „: “ ohne Anführungszeichen")
                data[key] = value
        for key in ("name", "description"):
            if not data.get(key):
                fail(f"{label}: `{key}` fehlt oder ist leer")


def check_scripts():
    for path in ROOT.glob("scripts/*.py"):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as error:
            fail(f"{path.name}: {error.msg}")


def check_doc_references():
    names = {path.stem for path in ROOT.glob("docs/*.md")}
    for path in [*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("agents/*.md"),
                 *ROOT.glob("docs/*.md")]:
        for name in re.findall(r"loop-doc ([a-z-]+)", path.read_text(encoding="utf-8")):
            if name not in names:
                fail(f"{path.relative_to(ROOT).as_posix()}: `loop-doc {name}` gibt es nicht")


def check_hook():
    hook = ROOT / "scripts" / "session_start.py"
    with tempfile.TemporaryDirectory() as scratch:
        env = dict(os.environ, HOME=scratch, USERPROFILE=scratch)
        unbound = Path(scratch) / "unbound"
        bound = Path(scratch) / "bound"
        for repo in (unbound, bound):
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (bound / ".claude").mkdir()
        (bound / ".claude" / "ouroboros.json").write_text('{"permissions": {"*": "yes"}}',
                                                              encoding="utf-8")
        quiet = subprocess.run([sys.executable, str(hook)], cwd=unbound, env=env,
                               capture_output=True, text=True, encoding="utf-8")
        if quiet.returncode or quiet.stdout.strip():
            fail(f"Hook ohne Loop nicht still: {quiet.stdout[:200]} {quiet.stderr[:200]}")
        loud = subprocess.run([sys.executable, str(hook)], cwd=bound, env=env,
                              capture_output=True, text=True, encoding="utf-8")
        try:
            context = json.loads(loud.stdout)["hookSpecificOutput"]["additionalContext"]
            if "# Delivery loop" not in context:
                fail("Hook mit Loop legt den Vertrag nicht in den Kontext")
        except (ValueError, KeyError):
            fail(f"Hook mit Loop schreibt kein gültiges JSON: {loud.stdout[:200]} "
                 f"{loud.stderr[:200]}")


def main():
    check_manifests()
    check_frontmatter()
    check_scripts()
    check_doc_references()
    check_hook()
    sys.stdout.reconfigure(encoding="utf-8")
    if errors:
        print("Selbstprüfung fehlgeschlagen:")
        print("\n".join(f"  - {error}" for error in errors))
        return 1
    print("Selbstprüfung bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
