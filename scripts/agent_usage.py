#!/usr/bin/env python3
"""Checks whether the cut of the agent roles fits what actually ran — across all repos that
run the loop.

The roles are one definition for many repos. So this script does not measure the repo it runs
in, but every repo in the registry (`~/.claude/ouroboros/projects.json`). A repo enters the
registry at the first SessionStart where the loop runs there — because the repo carries it
(`.claude/ouroboros.json`) or an answer is already remembered (`.git/ouroboros.json`). The
definitions and their change times come from the plugin's source repo.

The runs come from the transcripts under `~/.claude/projects/` — each repo's main sessions, the
sessions of its worktrees and the subagent runs inside them. What is measured is the amount of
context a run carried: fresh input plus cache. That is not a billing item but the volume every
turn reads again.

Nine checks:

1. **Dead definition** — a plugin agent that was spawned in no repo. Either the trigger is
   missing or the role is made up.
2. **Bypassed definition** — work that names a defined role but ran as `general-purpose`. Then
   that role's tool boundary does not hold: a Reviewer without `Edit` is only one if it is also
   spawned as a Reviewer.
3. **Candidate** — a role shape that recurs without a definition. This is the finding that
   proposes a new role.
4. **Wrong cut** — runs over the turn budget, under the minimum length, or with more base load
   than work.
5. **Not cut** — interactive sessions whose context per turn breaks the threshold. The talk went
   on where it should have been cut.
6. **Done in the main context** — tasks of the same shape that run long without a word from the
   stakeholder in an interactive session. Who does not interject is not having a conversation
   but has delegated without delegating. The shape is the role proposal: grouped by the
   triggers the loop already knows — an issue, a milestone step.
7. **Repeated orientation** — documents that nearly every run reads in full. They need no role
   profile of their own, but a distillate.
8. **Lock period** — a role whose definition changed is exempt from all findings until its fifth
   run after the change, counted across all repos. Before that, a finding measures the old
   version, not the new one. A run of a role is a subagent of its type, a session that loads its
   skill, or — from before the plugin — a session that reads its document under `docs/agents/`.
   What belongs to no role measures the loop itself: the same holds for it from the last change
   of `docs/loop.md`, counted in sessions.
9. **Pattern** — the attributions the Product Owner replies to stakeholder comments in PRs
   (`Attribution: <place> — …`, or the older German `Zuordnung: <Stelle> — …`). The same place
   in three PRs since the last change of its definition is a finding. Places that mean a role
   count across all repos. Places that mean the product ("rule missing", "spec") count per repo,
   because their receiver is that repo's Architect. The source is GitHub via `gh`; without a
   network the check drops out.

The findings are the Agent-Designer's source (skill `ouroboros:agent-designer`).

The thresholds are the default. A repo can override them for its own runs in
`.claude/ouroboros.json`, section `agentUsage` (e.g. `{"turnBudget": 60}`).

A time window is evaluated (`--since`, default 90 days). What is older is no longer a finding but
history.

No finding: no output, exit 0 — so it stays out of the way as a SessionStart hook.
With findings: report on stdout, exit 1. `--full` shows the state even without a finding.
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

# Thresholds. Each comes from a measurement on the loop's first repo, not from a recommendation.
LIMITS = {
    "turnBudget": 40,          # The longest run took 96 turns - that is a session without a human.
    "minTurns": 3,             # Below that a run carries little but its base: 38k before the first word.
    "sessionContext": 250_000, # A session's median was 141k; above this, nobody cut.
    "unattendedTurns": 25,     # This long without a word is a task, not a conversation.
}
BLOCK_FLOOR = 10          # Shorter stretches are conversation; they don't even enter the cache.
CANDIDATE_RUNS = 3        # Three times the same shape is a role, twice is chance.
ORIENTATION_SHARE = 0.5   # A document that half of all runs read in full.
WINDOW_DAYS = 90          # Older runs are history, not a finding.
HOOK_BUDGET_SECONDS = 5   # What one run does not read in, the next one catches up on.
CACHE_VERSION = 7         # Discard on new fields or labels instead of mixing halves.
SHOWN_PER_FINDING = 3     # Outliers are sorted; the heaviest are enough.
LOCK_RUNS = 5             # This many runs a changed definition needs before it can be a finding.
PATTERN_PRS = 3           # The same attribution in this many PRs is a pattern, fewer is a one-off.
GITHUB_TIMEOUT = 4        # The hook has its time budget; reading the transcripts takes up to 5.

# Place from the attribution → the definition whose change restarts the count.
# ("plugin", path) lives in the plugin's source repo, ("project", path) in the PR's repo.
# "nobody" is QA as intended; "gap" has no definition yet. German places map onto these
# (`loopcfg.place_of`).
ATTRIBUTIONS = {
    "developer": ("plugin", "agents/developer.md"),
    "reviewer": ("plugin", "agents/reviewer.md"),
    "rule missing": ("project", "docs/code-principles.md"),
    "spec": ("plugin", "skills/architect/SKILL.md"),
    "cut": ("plugin", "skills/product-owner/SKILL.md"),
    "gap": None,
}
TO_ARCHITECT = {"rule missing", "spec"}
LOOP = "Loop (docs/loop.md)"
LOOP_DEFINITION = "docs/loop.md"
NOT_A_ROLE = {"setup"}
PREFIXES = "|".join(loopcfg.ATTRIBUTION_PREFIXES)
ATTRIBUTION = re.compile(rf"^\s*(?:{PREFIXES}):\s*([^—–\-\n]+)", re.IGNORECASE)
PULL_NUMBER = re.compile(r"/pull/(\d+)")
PREFIX = loopcfg.PLUGIN_NAME + ":"

DOC_PATH = re.compile(r"[\w./-]+\.md\b")
SKIPPED_DIRS = (".claude/worktrees", "Library", "node_modules", ".git", "Temp", "Logs")


def plain(name):
    """`ouroboros:developer` and the old `developer` are the same role."""
    if not name:
        return name
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def transcripts(project):
    """Every transcript of a repo with its origin: an interactive session or a subagent run.
    Worktrees live under the same prefix as their main checkout."""
    base = Path.home() / ".claude" / "projects"
    slug = loopcfg.project_slug(project)
    for directory in sorted(d for d in base.glob(slug + "*") if d.is_dir()):
        rest = directory.name[len(slug):]
        if rest and not rest.startswith("--claude-worktrees"):
            continue  # another repo whose path merely starts the same
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
    """A path as it appears in a tool call — relative, or absolute in some worktree — as a path
    in the repo."""
    relative = match.lstrip("./")
    if relative in known_docs:
        return relative
    tail = re.sub(r"^.*?/\.claude/worktrees/[^/]+/", "", match)
    for doc in known_docs:
        if tail == doc or tail.endswith("/" + doc):
            return doc
    return None


def markdown_in(project):
    """A repo's documents, without worktrees and build directories."""
    found = set()
    for path in project.rglob("*.md"):
        relative = path.relative_to(project).as_posix()
        if not relative.startswith(SKIPPED_DIRS):
            found.add(relative)
    return found


def collect(projects, known, cache_path, budget=None):
    """Transcripts only grow at the end; a run of the same size is the same run."""
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get("version") != CACHE_VERSION:
        cache = {"version": CACHE_VERSION, "entries": {}}
    entries = cache["entries"]
    runs, sessions, pending = [], [], 0
    deadline = time.monotonic() + budget if budget else None
    # The role documents from before the plugin, so a run from back then is assigned to its
    # role even if the repo no longer has the file.
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
    """What a task looks like. The shapes are the loop's own, not made up."""
    if not prompt or prompt.lstrip().startswith(("<system-reminder>", "<command-message>")):
        return None
    if ISSUE_TRIGGER.search(prompt):
        return "an issue"
    if STEP_TRIGGER.search(prompt):
        return "a milestone step"
    return None


def roles():
    """The roles the plugin knows — defined as a subagent or documented as a skill."""
    root = loopcfg.definitions_root()
    known = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        if path.parent.name not in NOT_A_ROLE:
            known[path.parent.name] = "documented"
    for path in sorted((root / "agents").glob("*.md")):
        known[path.stem] = "defined"
    return known


def definition_of(slug, source):
    return f"agents/{slug}.md" if source == "defined" else f"skills/{slug}/SKILL.md"


def changed_at(root, relative):
    """The last commit on the file, in UTC and written like the transcripts' timestamps, so a
    text comparison is enough."""
    if root is None:
        return None
    stamp = loopcfg.git(["log", "-1", "--format=%cI", "--", relative], cwd=root)
    if not stamp:
        return None
    return datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


_PLUGIN_STAMPS = {}


def plugin_changed_at(relative):
    """The last change of a plugin file: from a clone with full history, else — installed from
    GitHub, as a shallow clone or a copy — via the GitHub API."""
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
    """{slug: last change of its definition} — from the plugin's history."""
    found = {}
    for slug, kind in known.items():
        since = plugin_changed_at(definition_of(slug, kind))
        if since:
            found[slug] = since
    return found


def is_run_of(entry, slug, source):
    """A defined role runs only when it is spawned — whoever reads its file is editing it. A
    documented role runs when a session loads its skill or, before the plugin, read its
    document."""
    if source == "defined":
        return entry["agent"] == slug
    return (entry["agent"] == slug or slug in entry.get("skills", [])
            or f"docs/agents/{slug}.md" in entry["docs"])


def locks(known, changed, runs, sessions):
    """{slug: (changed, runs since)} for every role whose lock period is not over yet."""
    locked = {}
    for slug, since in changed.items():
        count = sum(1 for entry in runs + sessions
                    if entry["last"] >= since and is_run_of(entry, slug, known[slug]))
        if count < LOCK_RUNS:
            locked[slug] = (since, count)
    return locked


def attributions(projects, window_days):
    """[(time, repo, PR, place, text)] from the review and conversation comments of all repos
    and from the notes of `loop-note`, for repos where no PR reply may stand. None means: GitHub
    unreachable and no note."""
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
        place = loopcfg.place_of(note.get("place"))
        if project is None or place not in ATTRIBUTIONS or (note.get("at") or "") < since:
            continue
        pull = PULL_NUMBER.search(note.get("ref") or "")
        found.append((note["at"], project, int(pull.group(1)) if pull else note.get("ref"),
                      place, note.get("text") or ""))
    return found


def github_attributions(projects, window_days):
    """The attributions that stand as a reply in a PR. A repo GitHub does not answer for drops
    out, not the whole check."""
    since = (datetime.now(timezone.utc) - timedelta(days=window_days or 3650)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    select = (f'.[] | select(.body | test("^\\\\s*({PREFIXES}):"; "i")) '
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
                place = loopcfg.place_of(match.group(1))
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
    """Places named in PATTERN_PRS PRs since the last change of their definition. A place that
    means the product counts per repo, all others across all repos."""
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
        receiver = (f"Architect of {Path(project).name}, as needs-refinement"
                    if place in TO_ARCHITECT else "Agent-Designer")
        numbers = ", ".join(f"{Path(repo).name}#{pull}" if isinstance(pull, int)
                            else f"{Path(repo).name} {pull}"
                            for repo, pull in sorted(pulls, key=str))
        findings.append((f"Pattern: \"{place}\" in {len(pulls)} PRs → {receiver}",
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
    """The shape of a run: what stands before the colon is the role that was meant."""
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
    """The threshold for a run: the default, or what its repo sets for it."""
    return overrides.get(entry["project"], {}).get(name, LIMITS[name])


def repos_of(entries):
    names = sorted({entry["repo"] for entry in entries})
    return f" [{', '.join(names)}]" if names else ""


def check(known, runs, sessions, window_days, changed, locked, loop_since, overrides):
    defined = {slug for slug, source in known.items() if source == "defined"} - set(locked)
    runs, sessions = recent(runs, window_days), recent(sessions, window_days)
    # A run before the last change of its role measures a version that no longer exists.
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
        findings.append(("Dead definition",
                         [f"{slug}: spawned in no repo, agents/{slug}.md"]))

    bypassed, shapes = defaultdict(list), defaultdict(list)
    for entry in runs:
        slug = role_of(entry["description"], known)
        if slug and slug in defined and entry["agent"] != slug:
            bypassed[slug].append(entry)
        elif not slug and shape_of(entry["description"]):
            shapes[shape_of(entry["description"])].append(entry)
    for slug, entries in sorted(bypassed.items()):
        agents = ", ".join(sorted({entry["agent"] or "?" for entry in entries}))
        findings.append(("Bypassed definition",
                         [f"{slug}: {len(entries)} runs as {agents} - its tool boundary "
                          f"did not hold{repos_of(entries)}"]))
    for shape, entries in sorted(shapes.items()):
        if len(entries) < CANDIDATE_RUNS:
            continue
        source = known.get(shape.replace(" ", "-"))
        note = f"in the plugin, {source}" if source else "documented nowhere"
        findings.append(("Candidate",
                         [f"\"{shape}\": {len(entries)} runs, "
                          f"{tokens(sum(entry['total'] for entry in entries))}, {note}"
                          f"{repos_of(entries)}"]))

    oversized = [entry for entry in runs if entry["turns"] > limit(entry, "turnBudget", overrides)]
    if oversized:
        findings.append((f"Wrong cut: {len(oversized)} of {len(runs)} runs over "
                         f"the turn budget", [label(entry) for entry in
                                              sorted(oversized, key=lambda e: -e["turns"])]))
    stunted = [entry for entry in runs if entry["turns"] < limit(entry, "minTurns", overrides)]
    if stunted:
        findings.append((f"Base without work: {len(stunted)} runs under the minimum length",
                         [label(entry) for entry in stunted]))

    swollen = [entry for entry in sessions
               if entry["peak"] > limit(entry, "sessionContext", overrides)]
    if swollen:
        findings.append((f"Not cut: {len(swollen)} sessions over the context threshold",
                         [f"{entry['repo']} \"{session_name(entry)}\": {entry['turns']} turns, "
                          f"peak {tokens(entry['peak'])}" for entry in
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
        findings.append((f"Done in the main context: {len(lengths)} blocks on \"{trigger}\"",
                         [f"ø {sum(lengths) / len(lengths):.0f} turns without a word, longest "
                          f"{max(lengths)} - a role carries the same work cheaper"
                          f"{repos_of([entry for _, entry in items])}"]))

    if runs:
        orientation = Counter()
        for entry in runs:
            orientation.update(f"{entry['repo']}: {doc}" for doc in entry["docs"])
        repeated = [f"{document}: read in {count} of {len(runs)} runs"
                    for document, count in orientation.most_common()
                    if count / len(runs) >= ORIENTATION_SHARE]
        if repeated:
            findings.append(("Repeated orientation", repeated))
    return findings


def label(entry):
    return f"{entry['repo']} {entry['agent'] or '?'} \"{(entry['description'] or '')[:40]}\": " \
           f"{entry['turns']} turns, {tokens(entry['total'])}"


def session_name(entry):
    return (entry["title"] or Path(entry["path"]).stem[:8])[:46]


def tokens(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    return f"{value // 1000}k"


def overview(projects, runs, sessions, locked, found):
    lines = ["State:", "  Repos: " + ", ".join(str(p) for p in projects)]
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
    lines.append("  Runs per type:")
    for agent, entries in sorted(by_agent.items(), key=lambda item: -sum(e["total"] for e in item[1])):
        spend = sum(e["total"] for e in entries)
        turns = sum(e["turns"] for e in entries) / len(entries)
        lines.append(f"    {agent:18} {len(entries):3} runs  {tokens(spend):>9}  "
                     f"ø {turns:.0f} turns{repos_of(entries)}")
    if locked:
        lines.append(f"  In lock period (under {LOCK_RUNS} runs since the last change):")
        for slug, (since, count) in sorted(locked.items()):
            lines.append(f"    {slug:18} since {since[:10]}, {count} runs")
    if found is None:
        lines.append("  Attributions: GitHub unreachable")
    else:
        counted = Counter(place for _, _, _, place, _ in found)
        summary = ", ".join(f"{place} {count}" for place, count in counted.most_common())
        lines.append(f"  Attributions: {summary or 'none'}")
    return "\n".join(lines)


def report(findings, compact):
    """Readable when called by hand. As a hook only the heaviest cases per finding, so the
    report does not fill the session context."""
    lines = ["Agent cut is off (plugin ouroboros, all repos):"]
    grouped = defaultdict(list)
    for kind, texts in findings:
        grouped[kind].extend(texts)
    for kind, texts in grouped.items():
        lines.append(f"  - {kind}")
        shown = texts[:SHOWN_PER_FINDING] if compact else texts
        lines.extend(f"      {text}" for text in shown)
        if compact and len(texts) > SHOWN_PER_FINDING:
            lines.append(f"      … {len(texts) - SHOWN_PER_FINDING} more")
    if compact:
        lines.append("  Details: agent-usage --full. Owner: Agent-Designer, in the plugin repo.")
    return "\n".join(lines)


def projects_to_measure(root):
    """All registered repos, plus the current one if it is bound and still missing."""
    projects = loopcfg.registered()
    if loopcfg.is_active(root):
        current = loopcfg.main_checkout(root)
        if not any(loopcfg.same_path(current, p) for p in projects):
            projects.append(current)
    return projects


def measure(root, window_days=WINDOW_DAYS, budget=None):
    """(repos, runs, sessions, pending, locks, findings, attributions)."""
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
                        help="show the state and all findings, even without a finding")
    parser.add_argument("--since", type=int, default=WINDOW_DAYS, metavar="DAYS",
                        help=f"window in which a run still counts as a finding "
                             f"(default: {WINDOW_DAYS}, 0 for all)")
    parser.add_argument("--hook", action="store_true",
                        help="output as SessionStart hook JSON instead of text, always exit 0 - "
                             "the finding belongs in the session context, it must not abort a "
                             "session.")
    args = parser.parse_args()

    root = loopcfg.project_root()
    try:
        projects, runs, sessions, pending, locked, findings, found = measure(
            root, args.since, HOOK_BUDGET_SECONDS if args.hook else None)
    except OSError as error:
        print(f"agent-usage: skipped ({error})", file=sys.stderr)
        return 0

    if args.hook:
        if findings:
            message = report(findings, compact=True)
            print(json.dumps({"systemMessage": message,
                              "hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": message}}))
        return 0

    if not projects:
        print("No repo in the registry. A repo enters it as soon as a session starts there "
              "in which the loop runs.")
        return 0
    if args.full:
        print(overview(projects, runs, sessions, locked, found))
        if pending:
            print(f"  ({pending} transcripts not read in yet)")
        print()
    if not findings:
        if args.full:
            print(f"Cut fits: in {args.since or 'all'} days no dead definition, "
                  f"no candidate, no outlier.")

        return 0
    print(report(findings, compact=False))
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
