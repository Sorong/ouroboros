#!/usr/bin/env python3
"""The plugin's shell commands, one entry each in `bin/`:

- `loop-permission` — shows what is allowed, denied or still open in the current repo.
- `loop-permission <kind> <yes|no>` — remembers an answer in the clone (`.git/ouroboros.json`).
  That way a question is asked only once. See `loop-doc permissions`.
- `loop-note <PR-URL|branch> <place> <reason>` — an attribution that must not stand as a PR
  reply. Lands in `~/.claude/ouroboros/attributions.jsonl`; `agent-usage` counts it like a PR
  reply. The German place names are accepted as well.
"""

import json
import sys
from datetime import datetime, timezone

import loopcfg


def permission(args):
    root = loopcfg.project_root()
    if not args:
        decided = loopcfg.permissions(root)
        for answer, label in (("yes", "allowed"), ("no", "denied"), (None, "open, ask")):
            kinds = [kind for kind, value in decided.items() if value == answer]
            if kinds:
                print(f"{label}: {', '.join(kinds)}")
        return 0
    if len(args) != 2 or args[0] not in loopcfg.KINDS or args[1] not in loopcfg.ANSWERS:
        print("loop-permission [<kind> <yes|no>], kind: " + ", ".join(loopcfg.KINDS))
        return 2
    kind, value = args
    current = loopcfg.permissions(root)[kind]
    if current == value:
        print(f"{kind}: {value} already holds.")
        return 0
    repo = loopcfg.config(root, "permissions")
    if repo.get(kind, repo.get("*")) in loopcfg.ANSWERS:
        print(f"{kind} is set by the repo itself ({loopcfg.repo_config_path(root)}): {current}. "
              f"A remembered answer would not override it.")
        return 1
    print(f"{kind}: {value} → {loopcfg.set_permission(root, kind, value)}")
    return 0


def note(args):
    place = loopcfg.place_of(args[1]) if len(args) == 3 else None
    if place is None:
        print("loop-note <PR-URL|branch> <place> <reason>, place: " + ", ".join(loopcfg.PLACES))
        return 2
    root = loopcfg.project_root()
    ref, _, text = args
    entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "repo": loopcfg.repo_id(root), "ref": ref, "place": place,
             "text": f"Attribution: {place} — {text}"}
    loopcfg.HOME.mkdir(parents=True, exist_ok=True)
    with loopcfg.NOTES.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"Attribution noted: {loopcfg.NOTES}")
    return 0


COMMANDS = {"permission": permission, "note": note}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]))
