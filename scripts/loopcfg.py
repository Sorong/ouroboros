"""What all of the plugin's checks share: the project root, a repo's settings, the remembered
permissions, the registry of repos that run the loop, the attribution places, and the plugin's
source.

A repo knows two places for the loop, both optional:

- `.claude/ouroboros.json` in the repo — for a repo that carries the loop itself: permissions for
  everyone, thresholds for the checks. Only then do the roadmap and house-style checks run.
- `.git/ouroboros.json` in the clone — the answers the stakeholder gave once
  (`loop-doc permissions`). Git does not version what lives under `.git`: a foreign repo stays
  untouched, and all worktrees of the clone see the same answers.

Whatever else a project knows about itself — test command, language, pitfalls — lives in its own
CLAUDE.md and docs, not here.

The plugin runs as a copy in Claude Code's cache. The roles change in its source repo, though,
and only there does Git have their history. That is why this module tells the root of the copy
(`PLUGIN_ROOT`) apart from the source (`plugin_source()`).
"""

import json
import os
import re
import subprocess
from pathlib import Path

PLUGIN_NAME = "ouroboros"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(".claude") / "ouroboros.json"
LOCAL = "ouroboros.json"
HOME = Path.home() / ".claude" / PLUGIN_NAME
REGISTRY = HOME / "projects.json"
NOTES = HOME / "attributions.jsonl"
KINDS = ("push", "pr", "issues", "labels", "pr-comments", "adr", "context", "roadmap",
         "principles")
ANSWERS = ("yes", "no")

# The places an attribution can name (`Attribution: <place> — …`). The German forms were the
# original ones; PR replies and notes written with them still count, as the same place.
PLACES = ("nobody", "developer", "reviewer", "rule missing", "spec", "cut", "gap")
PLACE_ALIASES = {"niemand": "nobody", "regel fehlt": "rule missing", "schnitt": "cut",
                 "lücke": "gap"}
ATTRIBUTION_PREFIXES = ("Attribution", "Zuordnung")


def place_of(text):
    """The canonical place for a place as written, in either language; None if it is none."""
    place = " ".join((text or "").split()).lower()
    place = PLACE_ALIASES.get(place, place)
    return place if place in PLACES else None


def git(args, cwd, timeout=5):
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def project_root(start=None):
    """The root of the checkout the session runs in. In a worktree that is the worktree, not the
    main checkout."""
    start = start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    top = git(["rev-parse", "--show-toplevel"], cwd=start)
    return Path(top) if top else Path(start)


def main_checkout(root):
    """From inside a worktree, the main checkout — that is where registry and transcripts live."""
    common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root)
    return Path(common).parent if common else Path(root)


REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def repo_id(root):
    """`owner__repo` from the `origin` remote, else the name of the main checkout. The same on
    every device — the key under which `loop-note` assigns an attribution to a repo."""
    url = git(["remote", "get-url", "origin"], cwd=root)
    match = REMOTE.search(url) if url else None
    if match:
        return f"{match.group(1)}__{match.group(2)}"
    return main_checkout(root).name


def git_dir(root):
    """The clone's shared `.git` — from inside a worktree, the main checkout's."""
    common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root)
    return Path(common) if common else Path(root) / ".git"


def _read_json(path):
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def repo_config_path(root):
    for base in (Path(root), main_checkout(root)):
        if (base / CONFIG).is_file():
            return base / CONFIG
    return None


def carries_loop(root):
    """Does the repo carry the loop itself? Then it has `.claude/ouroboros.json`."""
    return repo_config_path(root) is not None


def local_path(root):
    return git_dir(root) / LOCAL


def is_active(root):
    """Does the loop run in this repo? Yes if the repo carries it or an answer was already
    remembered here."""
    return carries_loop(root) or local_path(root).is_file()


def config(root, section):
    """One section of the repo's `.claude/ouroboros.json`."""
    path = repo_config_path(root)
    value = (_read_json(path) or {}).get(section) if path else None
    return value if isinstance(value, dict) else {}


def permissions(root):
    """{kind: yes|no|None}. What the repo sets for everyone holds; else the remembered answer;
    else None — open, so ask."""
    decided = {kind: None for kind in KINDS}
    local = (_read_json(local_path(root)) or {}).get("permissions") or {}
    repo = config(root, "permissions")
    for kind in KINDS:
        for source in (repo, local):
            value = source.get(kind, source.get("*"))
            if value in ANSWERS:
                decided[kind] = value
                break
    return decided


def set_permission(root, kind, value):
    """Remembers an answer in the clone and returns the path."""
    path = local_path(root)
    data = _read_json(path) or {}
    data.setdefault("repo", repo_id(root))
    data.setdefault("permissions", {})[kind] = value
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def notes():
    """[{at, repo, ref, place, text}] — attributions that must not stand as a PR reply."""
    try:
        lines = NOTES.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def same_path(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _norm(path):
    return str(Path(path)).replace("\\", "/").rstrip("/").lower()


def registered():
    """The main checkouts the loop has run in before and that still exist."""
    try:
        paths = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Path(p) for p in paths if is_active(p)]


def register(root):
    """Remembers the main checkout. Every SessionStart in a repo with the loop calls this, so
    `agent-usage` knows which repos it has to read across all roles."""
    checkout = main_checkout(root)
    try:
        paths = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        paths = []
    if _norm(checkout) in {_norm(p) for p in paths}:
        return
    paths.append(str(checkout))
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(sorted(paths), indent=2), encoding="utf-8")
    except OSError:
        pass


def _is_source(path):
    """A clone of the plugin with full history. A shallow clone knows only its last commit;
    every file in it would look freshly changed."""
    manifest = Path(path) / ".claude-plugin" / "plugin.json"
    try:
        named = json.loads(manifest.read_text(encoding="utf-8")).get("name") == PLUGIN_NAME
    except (OSError, ValueError):
        return False
    return named and (Path(path) / ".git").exists() \
        and git(["rev-parse", "--is-shallow-repository"], cwd=path) == "false"


def plugin_repository():
    """The plugin's `owner/repo` on GitHub, from the manifest."""
    try:
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return None
    match = REMOTE.search(manifest.get("repository") or "")
    return f"{match.group(1)}/{match.group(2)}" if match else None


def plugin_source():
    """A clone of the plugin with full history: `OUROBOROS_SOURCE`, else the repo the session
    runs in — the Agent-Designer's session —, else the marketplace it was installed from, else
    the copy itself (`--plugin-dir`). Installed from GitHub, the marketplace is a shallow clone
    and does not count; then there is no source, and the change times come from the GitHub
    API."""
    candidates = []
    if os.environ.get("OUROBOROS_SOURCE"):
        candidates.append(Path(os.environ["OUROBOROS_SOURCE"]))
    candidates.append(main_checkout(project_root()))
    known = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"
    try:
        for entry in json.loads(known.read_text(encoding="utf-8")).values():
            source = entry.get("source") or {}
            for key in ("path", "installLocation"):
                value = source.get(key) if key == "path" else entry.get(key)
                if value:
                    candidates.append(Path(value))
    except (OSError, ValueError, AttributeError):
        pass
    candidates.append(PLUGIN_ROOT)
    for candidate in candidates:
        if _is_source(candidate):
            return candidate
    return None


def definitions_root():
    """Where the roles are read: the source if there is one, else the installed copy."""
    return plugin_source() or PLUGIN_ROOT


def project_slug(path):
    """The directory name under which Claude Code stores a path's transcripts."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))
