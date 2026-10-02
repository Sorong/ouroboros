"""Was alle Prüfungen des Plugins gemeinsam brauchen: die Projektwurzel, die Einstellungen eines
Repos, die gemerkten Erlaubnisse, das Register der Repos, die den Loop fahren, und die Quelle des
Plugins.

Ein Repo kennt zwei Orte für den Loop, beide optional:

- `.claude/ouroboros.json` im Repo — für ein Repo, das den Loop selbst trägt: Erlaubnisse für
  alle, Schwellen der Prüfungen. Nur dann laufen Roadmap- und Hausstil-Prüfung.
- `.git/ouroboros.json` im Clone — die Antworten, die der Stakeholder einmal gegeben hat
  (`loop-doc permissions`). Was unter `.git` liegt, versioniert Git nicht: ein fremdes Repo
  bleibt unberührt, und alle Worktrees des Clones sehen dieselben Antworten.

Was ein Projekt sonst über sich weiß — Testbefehl, Sprache, Fallen — steht in seiner eigenen
CLAUDE.md und Doku, nicht hier.

Das Plugin läuft als Kopie im Cache von Claude Code. Die Rollen ändern sich aber in seinem
Quell-Repo, und nur dort hat Git ihre Geschichte. Darum unterscheidet dieses Modul zwischen der
Wurzel der Kopie (`PLUGIN_ROOT`) und der Quelle (`plugin_source()`).
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


def git(args, cwd, timeout=5):
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def project_root(start=None):
    """Die Wurzel des Checkouts, in dem die Session läuft. In einem Worktree ist das der
    Worktree, nicht der Haupt-Checkout."""
    start = start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    top = git(["rev-parse", "--show-toplevel"], cwd=start)
    return Path(top) if top else Path(start)


def main_checkout(root):
    """Aus einem Worktree heraus der Haupt-Checkout — dort liegen Register und Transkripte."""
    common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root)
    return Path(common).parent if common else Path(root)


REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def repo_id(root):
    """`owner__repo` aus der `origin`-Remote, sonst der Name des Haupt-Checkouts. Gleich auf
    jedem Gerät — der Schlüssel, unter dem `loop-note` eine Zuordnung einem Repo zuschreibt."""
    url = git(["remote", "get-url", "origin"], cwd=root)
    match = REMOTE.search(url) if url else None
    if match:
        return f"{match.group(1)}__{match.group(2)}"
    return main_checkout(root).name


def git_dir(root):
    """Das gemeinsame `.git` des Clones — aus einem Worktree heraus das des Haupt-Checkouts."""
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
    """Trägt das Repo den Loop selbst? Dann hat es `.claude/ouroboros.json`."""
    return repo_config_path(root) is not None


def local_path(root):
    return git_dir(root) / LOCAL


def is_active(root):
    """Läuft der Loop in diesem Repo? Ja, wenn es ihn trägt oder hier schon einmal eine Antwort
    gemerkt wurde."""
    return carries_loop(root) or local_path(root).is_file()


def config(root, section):
    """Ein Abschnitt aus `.claude/ouroboros.json` des Repos."""
    path = repo_config_path(root)
    value = (_read_json(path) or {}).get(section) if path else None
    return value if isinstance(value, dict) else {}


def permissions(root):
    """{Art: yes|no|None}. Was das Repo für alle festlegt, gilt; sonst die gemerkte Antwort;
    sonst None — offen, also fragen."""
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
    """Merkt eine Antwort im Clone und gibt den Pfad zurück."""
    path = local_path(root)
    data = _read_json(path) or {}
    data.setdefault("repo", repo_id(root))
    data.setdefault("permissions", {})[kind] = value
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def notes():
    """[{at, repo, ref, place, text}] — Zuordnungen, die nicht als PR-Antwort stehen dürfen."""
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
    """Die Haupt-Checkouts, in denen der Loop schon einmal lief und die es noch gibt."""
    try:
        paths = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Path(p) for p in paths if is_active(p)]


def register(root):
    """Merkt sich den Haupt-Checkout. Jeder SessionStart in einem Repo mit Loop ruft das,
    damit `agent-usage` weiß, welche Repos es über alle Rollen hinweg lesen muss."""
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
    """Ein Clone des Plugins mit voller Geschichte. Ein flacher Clone kennt nur seinen letzten
    Commit, jede Datei sähe darin frisch geändert aus."""
    manifest = Path(path) / ".claude-plugin" / "plugin.json"
    try:
        named = json.loads(manifest.read_text(encoding="utf-8")).get("name") == PLUGIN_NAME
    except (OSError, ValueError):
        return False
    return named and (Path(path) / ".git").exists() \
        and git(["rev-parse", "--is-shallow-repository"], cwd=path) == "false"


def plugin_repository():
    """`owner/repo` des Plugins auf GitHub, aus dem Manifest."""
    try:
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return None
    match = REMOTE.search(manifest.get("repository") or "")
    return f"{match.group(1)}/{match.group(2)}" if match else None


def plugin_source():
    """Das Quell-Repo des Plugins: `OUROBOROS_SOURCE`, sonst der Marktplatz, aus dem es
    installiert ist, sonst die Kopie selbst, wenn sie ein Git-Repo ist (`--plugin-dir`)."""
    candidates = []
    if os.environ.get("OUROBOROS_SOURCE"):
        candidates.append(Path(os.environ["OUROBOROS_SOURCE"]))
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
    """Wo die Rollen gelesen werden: die Quelle, wenn es sie gibt, sonst die installierte Kopie."""
    return plugin_source() or PLUGIN_ROOT


def project_slug(path):
    """Der Verzeichnisname, unter dem Claude Code die Transkripte eines Pfads ablegt."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))
