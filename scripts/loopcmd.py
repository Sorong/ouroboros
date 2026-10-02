#!/usr/bin/env python3
"""Befehle des Plugins für die Shell, je ein Eintrag in `bin/`:

- `loop-permission` — zeigt, was im aktuellen Repo erlaubt, verboten oder noch offen ist.
- `loop-permission <art> <yes|no>` — merkt eine Antwort im Clone (`.git/ouroboros.json`).
  So wird eine Frage nur einmal gestellt. Siehe `loop-doc permissions`.
- `loop-note <PR-URL|Branch> <Stelle> <Begründung>` — eine Zuordnung, die nicht als PR-Antwort
  stehen darf. Landet in `~/.claude/ouroboros/attributions.jsonl`, `agent-usage` zählt sie
  wie eine PR-Antwort.
"""

import json
import sys
from datetime import datetime, timezone

import loopcfg

PLACES = ("niemand", "developer", "reviewer", "regel fehlt", "spec", "schnitt", "lücke")


def permission(args):
    root = loopcfg.project_root()
    if not args:
        decided = loopcfg.permissions(root)
        for answer, label in (("yes", "erlaubt"), ("no", "verboten"), (None, "offen, fragen")):
            kinds = [kind for kind, value in decided.items() if value == answer]
            if kinds:
                print(f"{label}: {', '.join(kinds)}")
        return 0
    if len(args) != 2 or args[0] not in loopcfg.KINDS or args[1] not in loopcfg.ANSWERS:
        print("loop-permission [<art> <yes|no>], art: " + ", ".join(loopcfg.KINDS))
        return 2
    kind, value = args
    current = loopcfg.permissions(root)[kind]
    if current == value:
        print(f"{kind}: {value} gilt schon.")
        return 0
    repo = loopcfg.config(root, "permissions")
    if repo.get(kind, repo.get("*")) in loopcfg.ANSWERS:
        print(f"{kind} legt das Repo selbst fest ({loopcfg.repo_config_path(root)}): {current}. "
              f"Eine gemerkte Antwort käme dagegen nicht an.")
        return 1
    print(f"{kind}: {value} → {loopcfg.set_permission(root, kind, value)}")
    return 0


def note(args):
    if len(args) != 3 or args[1].lower() not in PLACES:
        print("loop-note <PR-URL|Branch> <Stelle> <Begründung>, Stelle: " + ", ".join(PLACES))
        return 2
    root = loopcfg.project_root()
    ref, place, text = args
    entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "repo": loopcfg.repo_id(root), "ref": ref, "place": place.lower(),
             "text": f"Zuordnung: {place} — {text}"}
    loopcfg.HOME.mkdir(parents=True, exist_ok=True)
    with loopcfg.NOTES.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"Zuordnung notiert: {loopcfg.NOTES}")
    return 0


COMMANDS = {"permission": permission, "note": note}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]))
