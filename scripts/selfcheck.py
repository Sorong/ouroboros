#!/usr/bin/env python3
"""Checks the plugin before it rolls out — locally and in CI.

Every commit on `main` is a new version (the manifest has no `version`, Claude Code takes the
commit). Whatever slips through here lands on every device at the next session start.

1. The manifests are valid JSON, and the plugin is named like the marketplace entry.
2. Every skill and every agent has frontmatter with `name` and `description`, and the
   frontmatter is valid YAML — a description containing ": " without quotes would otherwise
   arrive empty.
3. Every script compiles.
4. Every `loop-doc <name>` in the texts exists under `docs/`.
5. The hook, started by its command from `hooks/hooks.json`, stays silent in a repo without the
   loop and writes valid JSON in a throwaway repo that carries the loop.
6. Every command in `bin/` starts an existing script through `scripts/python.sh`, and runs.
7. Paths are read alike on every OS: a Windows path in a tool call still names the repo's
   document, and a Windows checkout finds its transcripts.
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
        fail("Manifest: the plugin.json name is missing from marketplace.json")
    if "version" in plugin:
        fail("Manifest: plugin.json has a version — then a commit does not count as an update")


def check_frontmatter():
    try:
        import yaml
    except ImportError:
        yaml = None
    for path in [*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("agents/*.md")]:
        block = frontmatter(path)
        label = path.relative_to(ROOT).as_posix()
        if block is None:
            fail(f"{label}: no frontmatter")
            continue
        if yaml is not None:
            try:
                data = yaml.safe_load(block)
            except yaml.YAMLError as error:
                fail(f"{label}: frontmatter is not YAML ({error})")
                continue
        else:  # without PyYAML: check the most common trap by hand
            data = {}
            for line in block.splitlines():
                key, _, value = line.partition(": ")
                if value and not value.startswith(('"', "'")) and ": " in value:
                    fail(f"{label}: `{key}` contains \": \" without quotes")
                data[key] = value
        for key in ("name", "description"):
            if not data.get(key):
                fail(f"{label}: `{key}` is missing or empty")


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
                fail(f"{path.relative_to(ROOT).as_posix()}: `loop-doc {name}` does not exist")


def check_hook():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    with tempfile.TemporaryDirectory() as scratch:
        env = dict(os.environ, HOME=scratch, USERPROFILE=scratch, CLAUDE_PLUGIN_ROOT=str(ROOT))
        unbound = Path(scratch) / "unbound"
        bound = Path(scratch) / "bound"
        for repo in (unbound, bound):
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (bound / ".claude").mkdir()
        (bound / ".claude" / "ouroboros.json").write_text('{"permissions": {"*": "yes"}}',
                                                              encoding="utf-8")
        quiet = subprocess.run(["sh", "-c", command], cwd=unbound, env=env,
                               capture_output=True, text=True, encoding="utf-8")
        if quiet.returncode or quiet.stdout.strip():
            fail(f"Hook not silent without the loop: {quiet.stdout[:200]} {quiet.stderr[:200]}")
        loud = subprocess.run(["sh", "-c", command], cwd=bound, env=env,
                              capture_output=True, text=True, encoding="utf-8")
        try:
            context = json.loads(loud.stdout)["hookSpecificOutput"]["additionalContext"]
            if "# Delivery loop" not in context:
                fail("Hook with the loop does not put the contract into the context")
        except (ValueError, KeyError):
            fail(f"Hook with the loop writes no valid JSON: {loud.stdout[:200]} "
                 f"{loud.stderr[:200]}")


def check_commands():
    launch = re.compile(r'^exec sh "\$\{0%/\*\}/\.\./scripts/python\.sh" (\w+\.py)\b', re.MULTILINE)
    for path in sorted(ROOT.glob("bin/*")):
        match = launch.search(path.read_text(encoding="utf-8"))
        if not match or not (ROOT / "scripts" / match.group(1)).is_file():
            fail(f"bin/{path.name}: does not start a script through scripts/python.sh")
    for command in (["loop-doc"], ["loop-doc", "loop"]):
        run = subprocess.run(["sh", str(ROOT / "bin" / command[0]), *command[1:]], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8")
        if run.returncode or not run.stdout.strip():
            fail(f"`{' '.join(command)}` fails: {run.stderr[:200]}")


def check_paths():
    sys.path.insert(0, str(ROOT / "scripts"))
    import agent_usage
    import loopcfg
    known = {"docs/loop.md"}
    for path in (r"C:\Users\me\repo\docs\loop.md",
                 r"C:\Users\me\repo\.claude\worktrees\fix\docs\loop.md",
                 "/home/me/repo/.claude/worktrees/fix/docs/loop.md", "docs/loop.md"):
        if agent_usage.docs_in({"file_path": path}, known) != known:
            fail(f"agent-usage does not recognise docs/loop.md in {path}")
    if loopcfg.project_slug(r"C:\Users\me\my_repo.x") != "C--Users-me-my-repo-x":
        fail("project_slug does not match Claude Code's folder for a Windows path")


def main():
    check_manifests()
    check_frontmatter()
    check_scripts()
    check_doc_references()
    check_hook()
    check_commands()
    check_paths()
    sys.stdout.reconfigure(encoding="utf-8")
    if errors:
        print("Self-check failed:")
        print("\n".join(f"  - {error}" for error in errors))
        return 1
    print("Self-check passed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
