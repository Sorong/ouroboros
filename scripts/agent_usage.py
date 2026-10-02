#!/usr/bin/env python3
"""Prüft, ob der Zuschnitt der Agent-Rollen zu dem passt, was tatsächlich gelaufen ist — über
alle Repos, die den Loop fahren.

Die Rollen sind eine Definition für viele Repos. Darum misst dieses Skript nicht das Repo, in
dem es läuft, sondern jedes Repo im Register (`~/.claude/ouroboros/projects.json`). Ins
Register kommt ein Repo beim ersten SessionStart, an dem der Loop dort läuft — weil das Repo ihn
trägt (`.claude/ouroboros.json`) oder schon eine Antwort gemerkt ist (`.git/ouroboros.json`). Die
Definitionen und ihre Änderungszeitpunkte kommen aus dem Quell-Repo des Plugins.

Quelle der Läufe sind die Transkripte unter `~/.claude/projects/` — die Hauptsessions jedes
Repos, die Sessions seiner Worktrees und die Subagent-Läufe darin. Gemessen wird die
Kontextmenge, die ein Lauf getragen hat: frische Eingabe plus Cache. Das ist kein
Rechnungsposten, sondern das Volumen, das jeder Turn erneut mitliest.

Neun Prüfungen:

1. **Tote Definition** — ein Agent des Plugins, der in keinem Repo gespawnt wurde. Entweder
   fehlt der Trigger oder die Rolle ist erfunden.
2. **Umgangene Definition** — Arbeit, die eine definierte Rolle beim Namen nennt, aber als
   `general-purpose` lief. Dann gilt deren Werkzeuggrenze nicht: ein Reviewer ohne `Edit` ist
   nur einer, wenn er auch als Reviewer gespawnt wird.
3. **Kandidat** — eine Rollenform, die wiederkehrt, ohne dass es eine Definition gibt. Das ist
   der Befund, der eine neue Rolle vorschlägt.
4. **Falscher Zuschnitt** — Läufe über dem Turn-Budget, unter der Mindestlänge oder mit mehr
   Sockel als Arbeit.
5. **Nicht geschnitten** — interaktive Sessions, deren Kontext pro Turn die Schwelle reißt.
   Dort wurde weitergeredet, wo hätte geschnitten werden müssen.
6. **Im Hauptkontext erledigt** — Aufträge derselben Form, die in einer interaktiven Session
   lange ohne Zuruf durchlaufen. Wer nicht dazwischenredet, führt kein Gespräch, sondern hat
   delegiert, ohne zu delegieren. Die Form ist der Rollenvorschlag: gruppiert wird nach den
   Triggern, die der Loop ohnehin kennt — ein Issue, ein Meilensteinschritt.
7. **Wiederholte Orientierung** — Dokumente, die fast jeder Lauf ganz liest. Die brauchen kein
   eigenes Rollenprofil, sondern ein Destillat.
8. **Sperrfrist** — eine Rolle, deren Definition sich geändert hat, ist bis zu ihrem fünften Lauf
   danach von allen Befunden ausgenommen, gezählt über alle Repos. Vorher misst ein Befund die
   alte Fassung, nicht die neue. Als Lauf einer Rolle zählt ein Subagent ihres Typs, eine
   Session, die ihren Skill lädt, oder — aus der Zeit vor dem Plugin — eine Session, die ihr
   Dokument unter `docs/agents/` liest. Was keiner Rolle gehört, misst den Loop selbst: für ihn
   gilt dasselbe ab der letzten Änderung von `docs/loop.md`, gezählt in Sessions.
9. **Muster** — die Zuordnungen, die der Product Owner auf Stakeholder-Kommentare in PRs antwortet
   (`Zuordnung: <Stelle> — …`). Dieselbe Stelle in drei PRs seit der letzten Änderung ihrer
   Definition ist ein Befund. Stellen, die eine Rolle meinen, zählen über alle Repos. Stellen,
   die das Produkt meinen („Regel fehlt", „Spec"), zählen je Repo, denn ihr Empfänger ist der
   Architect dieses Repos. Die Quelle ist GitHub über `gh`; ohne Netz fällt die Prüfung weg.

Die Befunde sind die Quelle des Agent-Designers (Skill `ouroboros:agent-designer`).

Die Schwellen sind die Vorgabe. Ein Repo kann sie für seine eigenen Läufe überschreiben, in
`.claude/ouroboros.json`, Abschnitt `agentUsage` (z. B. `{"turnBudget": 60}`).

Gewertet wird ein Zeitfenster (`--since`, Default 90 Tage). Was älter ist, ist kein Befund mehr,
sondern Geschichte.

Ohne Befund: keine Ausgabe, Exit 0 — damit es als SessionStart-Hook nicht stört.
Mit Befund: Bericht auf stdout, Exit 1. `--full` zeigt den Stand auch ohne Befund.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import loopcfg

# Schwellen. Jede stammt aus einer Messung am ersten Repo des Loops, nicht aus einer Empfehlung.
LIMITS = {
    "turnBudget": 40,          # Der längste Lauf brauchte 96 Turns - das ist eine Session ohne Mensch.
    "minTurns": 3,             # Darunter trägt der Lauf fast nur seinen Sockel: 38k vor dem ersten Wort.
    "sessionContext": 250_000, # Median einer Session lag bei 141k; darüber wurde nicht geschnitten.
    "unattendedTurns": 25,     # So lange ohne Zuruf ist ein Auftrag, kein Gespräch.
}
BLOCK_FLOOR = 10          # Kürzere Strecken sind Gespräch; sie kommen gar nicht erst in den Cache.
CANDIDATE_RUNS = 3        # Dreimal dieselbe Form ist eine Rolle, zweimal ein Zufall.
ORIENTATION_SHARE = 0.5   # Ein Dokument, das die Hälfte aller Läufe ganz liest.
WINDOW_DAYS = 90          # Ältere Läufe sind Geschichte, kein Befund.
HOOK_BUDGET_SECONDS = 5   # Was in einem Lauf nicht neu eingelesen wird, holt der nächste nach.
CACHE_VERSION = 6         # Bei neuen Feldern verwerfen, statt Halbes zu mischen.
SHOWN_PER_FINDING = 3     # Ausreißer sind sortiert; die schwersten genügen.
LOCK_RUNS = 5             # So viele Läufe braucht eine geänderte Definition, bevor sie Befund sein kann.
PATTERN_PRS = 3           # Dieselbe Zuordnung in so vielen PRs ist ein Muster, darunter ein Einzelfall.
GITHUB_TIMEOUT = 4        # Der Hook hat sein Zeitbudget; das Einlesen der Transkripte braucht bis zu 5.

# Stelle aus der Zuordnung → die Definition, deren Änderung die Zählung neu beginnen lässt.
# ("plugin", Pfad) liegt im Quell-Repo des Plugins, ("project", Pfad) im Repo des PRs.
# „niemand“ ist QA, wie sie gedacht ist; „Lücke“ hat noch keine Definition.
ATTRIBUTIONS = {
    "developer": ("plugin", "agents/developer.md"),
    "reviewer": ("plugin", "agents/reviewer.md"),
    "regel fehlt": ("project", "docs/code-principles.md"),
    "spec": ("plugin", "skills/architect/SKILL.md"),
    "schnitt": ("plugin", "skills/product-owner/SKILL.md"),
    "lücke": None,
}
TO_ARCHITECT = {"regel fehlt", "spec"}
LOOP = "Loop (docs/loop.md)"
LOOP_DEFINITION = "docs/loop.md"
NOT_A_ROLE = {"setup"}
ATTRIBUTION = re.compile(r"^\s*Zuordnung:\s*([^—–\-\n]+)", re.IGNORECASE)
PULL_NUMBER = re.compile(r"/pull/(\d+)")
PREFIX = loopcfg.PLUGIN_NAME + ":"

DOC_PATH = re.compile(r"[\w./-]+\.md\b")
SKIPPED_DIRS = (".claude/worktrees", "Library", "node_modules", ".git", "Temp", "Logs")


def plain(name):
    """`ouroboros:developer` und das alte `developer` sind dieselbe Rolle."""
    if not name:
        return name
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def transcripts(project):
    """Jedes Transkript eines Repos mit seiner Herkunft: eine interaktive Session oder ein
    Subagent-Lauf. Worktrees liegen unter demselben Präfix wie ihr Haupt-Checkout."""
    base = Path.home() / ".claude" / "projects"
    slug = loopcfg.project_slug(project)
    for directory in sorted(d for d in base.glob(slug + "*") if d.is_dir()):
        rest = directory.name[len(slug):]
        if rest and not rest.startswith("--claude-worktrees"):
            continue  # ein anderes Repo, dessen Pfad nur gleich anfängt
        kind = "worktree" if rest else "session"
        for path in directory.glob("*.jsonl"):
            yield path, kind, None
        for path in directory.glob("*/subagents/*.jsonl"):
            meta = path.with_suffix(".meta.json")
            yield path, "subagent", meta if meta.exists() else None


def scan(path, meta, known_docs):
    record = {"turns": 0, "total": 0, "first": 0, "peak": 0, "output": 0, "last": "",
              "title": None, "docs": [], "spawned": [], "skills": [], "agent": None,
              "description": None, "blocks": []}
    if meta:
        loaded = json.loads(meta.read_text(encoding="utf-8"))
        record["agent"] = plain(loaded.get("agentType"))
        record["description"] = loaded.get("description")
    docs, skills = set(), set()
    streak, prompt = 0, None

    def close_block(length, on):
        if length >= BLOCK_FLOOR:
            record["blocks"].append([length, trigger_of(on)])

    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") == "custom-title":
                record["title"] = entry.get("customTitle")
            if entry.get("type") == "user" and (entry.get("origin") or {}).get("kind") == "human":
                content = (entry.get("message") or {}).get("content")
                if isinstance(content, str):
                    close_block(streak, prompt)
                    prompt, streak = content, 0
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message") or {}
            usage = message.get("usage") or {}
            context = (usage.get("input_tokens", 0)
                       + usage.get("cache_read_input_tokens", 0)
                       + usage.get("cache_creation_input_tokens", 0))
            if not context:
                continue
            record["turns"] += 1
            record["total"] += context
            record["output"] += usage.get("output_tokens", 0)
            record["peak"] = max(record["peak"], context)
            record["last"] = entry.get("timestamp") or record["last"]
            if not record["first"]:
                record["first"] = context
            streak += 1
            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                arguments = block.get("input") or {}
                if block.get("name") in ("Task", "Agent"):
                    record["spawned"].append(plain(arguments.get("subagent_type", "?")))
                if block.get("name") == "Skill" and arguments.get("skill"):
                    skills.add(plain(arguments["skill"]))
                docs.update(filter(None, (repo_doc(match, known_docs)
                                          for match in DOC_PATH.findall(json.dumps(arguments)))))
    close_block(streak, prompt)
    record["docs"] = sorted(docs)
    record["skills"] = sorted(skills)
    return record


def repo_doc(match, known_docs):
    """Ein Pfad, wie er in einem Werkzeugaufruf steht — relativ, oder absolut in irgendeinem
    Worktree — als Pfad im Repo."""
    relative = match.lstrip("./")
    if relative in known_docs:
        return relative
    tail = re.sub(r"^.*?/\.claude/worktrees/[^/]+/", "", match)
    for doc in known_docs:
        if tail == doc or tail.endswith("/" + doc):
            return doc
    return None


def markdown_in(project):
    """Die Dokumente eines Repos, ohne Worktrees und Build-Verzeichnisse."""
    found = set()
    for path in project.rglob("*.md"):
        relative = path.relative_to(project).as_posix()
        if not relative.startswith(SKIPPED_DIRS):
            found.add(relative)
    return found


def collect(projects, known, cache_path, budget=None):
    """Transkripte wachsen nur am Ende; ein Lauf gleicher Größe ist derselbe Lauf."""
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get("version") != CACHE_VERSION:
        cache = {"version": CACHE_VERSION, "entries": {}}
    entries = cache["entries"]
    runs, sessions, pending = [], [], 0
    deadline = time.monotonic() + budget if budget else None
    # Die Rollendokumente aus der Zeit vor dem Plugin, damit ein Lauf von damals seiner Rolle
    # zugeordnet wird, auch wenn das Repo die Datei nicht mehr hat.
    legacy = {f"docs/agents/{slug}.md" for slug in known}
    for project in projects:
        known_docs = None
        for path, kind, meta in transcripts(project):
            key = str(path)
            size = path.stat().st_size
            cached = entries.get(key)
            if not cached or cached.get("size") != size:
                if deadline and time.monotonic() > deadline:
                    pending += 1
                    continue
                if known_docs is None:
                    known_docs = markdown_in(project) | legacy
                cached = {"size": size, "kind": kind, "record": scan(path, meta, known_docs)}
                entries[key] = cached
            entry = dict(cached["record"], kind=cached["kind"], path=key,
                         project=str(project), repo=project.name)
            (runs if cached["kind"] == "subagent" else sessions).append(entry)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return runs, sessions, pending


ISSUE_TRIGGER = re.compile(r"#\d+|issues/\d+")
STEP_TRIGGER = re.compile(r"\bM\d+(\.\d+)?\b", re.IGNORECASE)


def trigger_of(prompt):
    """Wonach ein Auftrag aussieht. Die Formen sind die aus dem Loop, nicht erfundene."""
    if not prompt or prompt.lstrip().startswith(("<system-reminder>", "<command-message>")):
        return None
    if ISSUE_TRIGGER.search(prompt):
        return "ein Issue"
    if STEP_TRIGGER.search(prompt):
        return "ein Meilensteinschritt"
    return None


def roles():
    """Was das Plugin an Rollen kennt — als Subagent definiert oder als Skill beschrieben."""
    root = loopcfg.definitions_root()
    known = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        if path.parent.name not in NOT_A_ROLE:
            known[path.parent.name] = "dokumentiert"
    for path in sorted((root / "agents").glob("*.md")):
        known[path.stem] = "definiert"
    return known


def definition_of(slug, source):
    return f"agents/{slug}.md" if source == "definiert" else f"skills/{slug}/SKILL.md"


def changed_at(root, relative):
    """Letzter Commit auf die Datei, in UTC und so geschrieben wie die Zeitstempel der Transkripte,
    damit ein Textvergleich genügt."""
    if root is None:
        return None
    stamp = loopcfg.git(["log", "-1", "--format=%cI", "--", relative], cwd=root)
    if not stamp:
        return None
    return datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


_PLUGIN_STAMPS = {}


def plugin_changed_at(relative):
    """Letzte Änderung einer Datei des Plugins: aus einem Clone mit voller Geschichte, sonst —
    installiert aus GitHub, als flacher Clone oder Kopie — über die GitHub-API."""
    if relative in _PLUGIN_STAMPS:
        return _PLUGIN_STAMPS[relative]
    source = loopcfg.plugin_source()
    stamp = changed_at(source, relative) if source else None
    repository = loopcfg.plugin_repository()
    if stamp is None and repository:
        try:
            output = subprocess.run(
                ["gh", "api", f"repos/{repository}/commits?path={relative}&per_page=1",
                 "--jq", ".[0].commit.committer.date"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=GITHUB_TIMEOUT).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            output = ""
        if output:
            stamp = datetime.fromisoformat(output.replace("Z", "+00:00")).astimezone(
                timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _PLUGIN_STAMPS[relative] = stamp
    return stamp


def changes(known):
    """{slug: letzte Änderung seiner Definition} — aus der Geschichte des Plugins."""
    found = {}
    for slug, kind in known.items():
        since = plugin_changed_at(definition_of(slug, kind))
        if since:
            found[slug] = since
    return found


def is_run_of(entry, slug, source):
    """Eine definierte Rolle läuft nur, wenn sie gespawnt wird — wer ihre Datei liest, bearbeitet
    sie. Eine beschriebene Rolle läuft, wenn eine Session ihren Skill lädt oder, vor dem Plugin,
    ihr Dokument las."""
    if source == "definiert":
        return entry["agent"] == slug
    return (entry["agent"] == slug or slug in entry.get("skills", [])
            or f"docs/agents/{slug}.md" in entry["docs"])


def locks(known, changed, runs, sessions):
    """{slug: (geändert, Läufe seither)} für jede Rolle, die ihre Sperrfrist noch nicht hinter
    sich hat."""
    locked = {}
    for slug, since in changed.items():
        count = sum(1 for entry in runs + sessions
                    if entry["last"] >= since and is_run_of(entry, slug, known[slug]))
        if count < LOCK_RUNS:
            locked[slug] = (since, count)
    return locked


def attributions(projects, window_days):
    """[(Zeitpunkt, Repo, PR, Stelle, Text)] aus Review- und Gesprächskommentaren aller Repos und
    aus den Notizen von `loop-note`, für Repos, in denen keine PR-Antwort stehen darf. None
    heißt: GitHub nicht erreichbar und keine Notiz."""
    noted = noted_attributions(projects, window_days)
    found = github_attributions(projects, window_days)
    if found is None:
        return noted or None
    return found + noted


def noted_attributions(projects, window_days):
    since = (datetime.now(timezone.utc) - timedelta(days=window_days or 3650)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    by_id = {loopcfg.repo_id(project): project for project in projects}
    found = []
    for note in loopcfg.notes():
        project = by_id.get(note.get("repo"))
        place = (note.get("place") or "").lower()
        if project is None or place not in ATTRIBUTIONS or (note.get("at") or "") < since:
            continue
        pull = PULL_NUMBER.search(note.get("ref") or "")
        found.append((note["at"], project, int(pull.group(1)) if pull else note.get("ref"),
                      place, note.get("text") or ""))
    return found


def github_attributions(projects, window_days):
    """Die Zuordnungen, die als Antwort in einem PR stehen. Ein Repo, das GitHub nicht
    beantwortet, fällt heraus, nicht die ganze Prüfung."""
    since = (datetime.now(timezone.utc) - timedelta(days=window_days or 3650)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    select = ('.[] | select(.body | test("^\\\\s*Zuordnung:"; "i")) '
              '| {at: .created_at, url: .html_url, body: .body}')
    calls = []
    try:
        for project in projects:
            for endpoint in ("pulls/comments", "issues/comments"):
                calls.append((project, subprocess.Popen(
                    ["gh", "api", "--paginate",
                     f"repos/{{owner}}/{{repo}}/{endpoint}?per_page=100&since={since}",
                     "--jq", select],
                    cwd=project, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    encoding="utf-8", errors="replace")))
    except OSError:
        for _, call in calls:
            call.kill()
        return None
    found, answered = [], 0
    deadline = time.monotonic() + GITHUB_TIMEOUT
    try:
        for project, call in calls:
            output, _ = call.communicate(timeout=max(0.1, deadline - time.monotonic()))
            if call.returncode:
                continue
            answered += 1
            for line in output.splitlines():
                comment = json.loads(line)
                pull = PULL_NUMBER.search(comment["url"] or "")
                match = ATTRIBUTION.match(comment["body"])
                if not pull or not match:
                    continue
                place = match.group(1).strip().lower()
                if place in ATTRIBUTIONS:
                    found.append((comment["at"], project, int(pull.group(1)), place,
                                  comment["body"].strip().splitlines()[0]))
    except (OSError, ValueError, subprocess.SubprocessError):
        for _, call in calls:
            call.kill()
        return None
    return found if answered else None


def defined_at(place, project):
    target = ATTRIBUTIONS[place]
    if target is None:
        return None
    scope, relative = target
    return plugin_changed_at(relative) if scope == "plugin" else changed_at(project, relative)


def patterns(found, locked):
    """Stellen, die in PATTERN_PRS PRs seit der letzten Änderung ihrer Definition genannt wurden.
    Eine Stelle, die das Produkt meint, zählt je Repo, alle anderen über alle Repos."""
    findings = []
    groups = defaultdict(dict)
    for at, project, pull, place, text in sorted(found, key=lambda item: item[0]):
        since = defined_at(place, project)
        if since and at < since:
            continue
        group = (place, project if place in TO_ARCHITECT else None)
        groups[group].setdefault((project, pull), text)
    for (place, project), pulls in sorted(groups.items(), key=lambda item: str(item[0])):
        if len(pulls) < PATTERN_PRS:
            continue
        target = ATTRIBUTIONS[place]
        slug = role_slug(target[1]) if target else None
        if slug in locked:
            continue
        receiver = (f"Architect von {Path(project).name}, als needs-refinement"
                    if place in TO_ARCHITECT else "Agent-Designer")
        numbers = ", ".join(f"{Path(repo).name}#{pull}" if isinstance(pull, int)
                            else f"{Path(repo).name} {pull}"
                            for repo, pull in sorted(pulls, key=str))
        findings.append((f"Muster: „{place}“ in {len(pulls)} PRs → {receiver}",
                         [numbers] + list(pulls.values())))
    return findings


def role_slug(relative):
    path = Path(relative)
    return path.parent.name if path.name == "SKILL.md" else path.stem


def role_of(description, known):
    if not description:
        return None
    text = description.lower()
    for slug in sorted(known, key=len, reverse=True):
        if slug.replace("-", " ") in text or slug in text:
            return slug
    return None


def role_of_run(entry, known):
    return entry["agent"] if entry["agent"] in known else role_of(entry["description"], known)


def shape_of(description):
    """Die Form eines Laufs: was vor dem Doppelpunkt steht, ist die Rolle, die gemeint war."""
    if not description or ":" not in description:
        return None
    head = description.split(":", 1)[0].strip().lower()
    return re.sub(r"[^a-zäöüß ]", "", head).strip() or None


def recent(entries, window_days):
    if not window_days:
        return entries
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    return [entry for entry in entries if entry["last"] >= cutoff]


def limit(entry, name, overrides):
    """Die Schwelle für einen Lauf: die Vorgabe, oder was sein Repo dafür setzt."""
    return overrides.get(entry["project"], {}).get(name, LIMITS[name])


def repos_of(entries):
    names = sorted({entry["repo"] for entry in entries})
    return f" [{', '.join(names)}]" if names else ""


def check(known, runs, sessions, window_days, changed, locked, loop_since, overrides):
    defined = {slug for slug, source in known.items() if source == "definiert"} - set(locked)
    runs, sessions = recent(runs, window_days), recent(sessions, window_days)
    # Ein Lauf vor der letzten Änderung seiner Rolle misst eine Fassung, die es nicht mehr gibt.
    def current(entry):
        slug = role_of_run(entry, known)
        if slug in changed:
            return slug not in locked and entry["last"] >= changed[slug]
        return LOOP not in locked and entry["last"] >= loop_since
    runs = [entry for entry in runs if current(entry)]
    sessions = [] if LOOP in locked else [entry for entry in sessions
                                          if entry["last"] >= loop_since]
    findings = []

    spawned = Counter()
    for entry in runs + sessions:
        spawned.update(entry["spawned"])
    for slug in sorted(defined - set(spawned)):
        findings.append(("Tote Definition",
                         [f"{slug}: in keinem Repo gespawnt, agents/{slug}.md"]))

    bypassed, shapes = defaultdict(list), defaultdict(list)
    for entry in runs:
        slug = role_of(entry["description"], known)
        if slug and slug in defined and entry["agent"] != slug:
            bypassed[slug].append(entry)
        elif not slug and shape_of(entry["description"]):
            shapes[shape_of(entry["description"])].append(entry)
    for slug, entries in sorted(bypassed.items()):
        agents = ", ".join(sorted({entry["agent"] or "?" for entry in entries}))
        findings.append(("Umgangene Definition",
                         [f"{slug}: {len(entries)} Läufe als {agents} - deren Werkzeuggrenze "
                          f"galt dabei nicht{repos_of(entries)}"]))
    for shape, entries in sorted(shapes.items()):
        if len(entries) < CANDIDATE_RUNS:
            continue
        source = known.get(shape.replace(" ", "-"))
        note = f"im Plugin {source}" if source else "nirgends beschrieben"
        findings.append(("Kandidat",
                         [f"„{shape}“: {len(entries)} Läufe, "
                          f"{tokens(sum(entry['total'] for entry in entries))}, {note}"
                          f"{repos_of(entries)}"]))

    oversized = [entry for entry in runs if entry["turns"] > limit(entry, "turnBudget", overrides)]
    if oversized:
        findings.append((f"Falscher Zuschnitt: {len(oversized)} von {len(runs)} Läufen über "
                         f"dem Turn-Budget", [label(entry) for entry in
                                              sorted(oversized, key=lambda e: -e["turns"])]))
    stunted = [entry for entry in runs if entry["turns"] < limit(entry, "minTurns", overrides)]
    if stunted:
        findings.append((f"Sockel ohne Arbeit: {len(stunted)} Läufe unter der Mindestlänge",
                         [label(entry) for entry in stunted]))

    swollen = [entry for entry in sessions
               if entry["peak"] > limit(entry, "sessionContext", overrides)]
    if swollen:
        findings.append((f"Nicht geschnitten: {len(swollen)} Sessions über der Kontextschwelle",
                         [f"{entry['repo']} „{session_name(entry)}“: {entry['turns']} Turns, "
                          f"Spitze {tokens(entry['peak'])}" for entry in
                          sorted(swollen, key=lambda e: -e["peak"])]))

    blocks = defaultdict(list)
    for entry in sessions:
        for length, trigger in entry["blocks"]:
            if trigger and length > limit(entry, "unattendedTurns", overrides):
                blocks[trigger].append((length, entry))
    for trigger, items in sorted(blocks.items(), key=lambda item: -len(item[1])):
        if len(items) < CANDIDATE_RUNS:
            continue
        lengths = [length for length, _ in items]
        findings.append((f"Im Hauptkontext erledigt: {len(lengths)} Blöcke auf „{trigger}“",
                         [f"ø {sum(lengths) / len(lengths):.0f} Turns ohne Zuruf, längster "
                          f"{max(lengths)} - dieselbe Arbeit trägt eine Rolle billiger"
                          f"{repos_of([entry for _, entry in items])}"]))

    if runs:
        orientation = Counter()
        for entry in runs:
            orientation.update(f"{entry['repo']}: {doc}" for doc in entry["docs"])
        repeated = [f"{document}: in {count} von {len(runs)} Läufen gelesen"
                    for document, count in orientation.most_common()
                    if count / len(runs) >= ORIENTATION_SHARE]
        if repeated:
            findings.append(("Wiederholte Orientierung", repeated))
    return findings


def label(entry):
    return f"{entry['repo']} {entry['agent'] or '?'} „{(entry['description'] or '')[:40]}“: " \
           f"{entry['turns']} Turns, {tokens(entry['total'])}"


def session_name(entry):
    return (entry["title"] or Path(entry["path"]).stem[:8])[:46]


def tokens(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} Mio"
    return f"{value // 1000}k"


def overview(projects, runs, sessions, locked, found):
    lines = ["Stand:", "  Repos: " + ", ".join(str(p) for p in projects)]
    by_kind = Counter()
    for entry in sessions:
        by_kind[entry["kind"]] += entry["total"]
    by_kind["subagent"] = sum(entry["total"] for entry in runs)
    total = sum(by_kind.values()) or 1
    for kind, value in by_kind.most_common():
        lines.append(f"  {kind:10} {tokens(value):>9}  {100 * value / total:4.1f}%")
    by_agent = defaultdict(list)
    for entry in runs:
        by_agent[entry["agent"] or "?"].append(entry)
    lines.append("  Läufe je Typ:")
    for agent, entries in sorted(by_agent.items(), key=lambda item: -sum(e["total"] for e in item[1])):
        spend = sum(e["total"] for e in entries)
        turns = sum(e["turns"] for e in entries) / len(entries)
        lines.append(f"    {agent:18} {len(entries):3} Läufe  {tokens(spend):>9}  "
                     f"ø {turns:.0f} Turns{repos_of(entries)}")
    if locked:
        lines.append(f"  In Sperrfrist (unter {LOCK_RUNS} Läufen seit der letzten Änderung):")
        for slug, (since, count) in sorted(locked.items()):
            lines.append(f"    {slug:18} seit {since[:10]}, {count} Läufe")
    if found is None:
        lines.append("  Zuordnungen: GitHub nicht erreichbar")
    else:
        counted = Counter(place for _, _, _, place, _ in found)
        summary = ", ".join(f"{place} {count}" for place, count in counted.most_common())
        lines.append(f"  Zuordnungen: {summary or 'keine'}")
    return "\n".join(lines)


def report(findings, compact):
    """Lesbar für den Aufruf von Hand. Als Hook je Befund nur die schwersten Fälle, damit der
    Bericht den Session-Kontext nicht füllt."""
    lines = ["Agent-Zuschnitt weicht ab (Plugin ouroboros, alle Repos):"]
    grouped = defaultdict(list)
    for kind, texts in findings:
        grouped[kind].extend(texts)
    for kind, texts in grouped.items():
        lines.append(f"  - {kind}")
        shown = texts[:SHOWN_PER_FINDING] if compact else texts
        lines.extend(f"      {text}" for text in shown)
        if compact and len(texts) > SHOWN_PER_FINDING:
            lines.append(f"      … {len(texts) - SHOWN_PER_FINDING} weitere")
    if compact:
        lines.append("  Details: agent-usage --full. Zuständig: Agent-Designer, im Plugin-Repo.")
    return "\n".join(lines)


def projects_to_measure(root):
    """Alle registrierten Repos, plus das aktuelle, falls es gebunden ist und noch fehlt."""
    projects = loopcfg.registered()
    if loopcfg.is_active(root):
        current = loopcfg.main_checkout(root)
        if not any(loopcfg.same_path(current, p) for p in projects):
            projects.append(current)
    return projects


def measure(root, window_days=WINDOW_DAYS, budget=None):
    """(Repos, Läufe, Sessions, ausstehend, Sperren, Befunde, Zuordnungen)."""
    projects = projects_to_measure(root)
    if not projects:
        return projects, [], [], 0, {}, [], []
    known = roles()
    runs, sessions, pending = collect(projects, known, loopcfg.HOME / "agent-usage.cache.json",
                                      budget)
    changed = changes(known)
    locked = locks(known, changed, runs, sessions)
    loop_since = plugin_changed_at(LOOP_DEFINITION) or ""
    loop_runs = sum(1 for entry in sessions if entry["last"] >= loop_since)
    if loop_runs < LOCK_RUNS:
        locked[LOOP] = (loop_since, loop_runs)
    overrides = {str(p): loopcfg.config(p, "agentUsage") for p in projects}
    findings = check(known, runs, sessions, window_days, changed, locked, loop_since, overrides)
    found = attributions(projects, window_days)
    findings += patterns(found or [], locked)
    return projects, runs, sessions, pending, locked, findings, found


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true",
                        help="Stand und alle Befunde zeigen, auch ohne Befund")
    parser.add_argument("--since", type=int, default=WINDOW_DAYS, metavar="TAGE",
                        help=f"Fenster, in dem ein Lauf noch als Befund zählt "
                             f"(Default: {WINDOW_DAYS}, 0 für alles)")
    parser.add_argument("--hook", action="store_true",
                        help="Ausgabe als SessionStart-Hook-JSON statt als Text, immer Exit 0 - "
                             "der Befund gehört in den Session-Kontext, er soll keine Session "
                             "abbrechen.")
    args = parser.parse_args()

    root = loopcfg.project_root()
    try:
        projects, runs, sessions, pending, locked, findings, found = measure(
            root, args.since, HOOK_BUDGET_SECONDS if args.hook else None)
    except OSError as error:
        print(f"agent-usage: übersprungen ({error})", file=sys.stderr)
        return 0

    if args.hook:
        if findings:
            message = report(findings, compact=True)
            print(json.dumps({"systemMessage": message,
                              "hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": message}}))
        return 0

    if not projects:
        print("Kein Repo im Register. Ein Repo kommt hinein, sobald dort eine Session startet, "
              "in der der Loop läuft.")
        return 0
    if args.full:
        print(overview(projects, runs, sessions, locked, found))
        if pending:
            print(f"  ({pending} Transkripte noch nicht eingelesen)")
        print()
    if not findings:
        if args.full:
            print(f"Zuschnitt passt: in {args.since or 'allen'} Tagen keine tote Definition, "
                  f"kein Kandidat, kein Ausreißer.")
        return 0
    print(report(findings, compact=False))
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
