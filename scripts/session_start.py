#!/usr/bin/env python3
"""SessionStart-Hook des Plugins.

In einem Repo, in dem der Loop läuft — es trägt ihn (`.claude/ouroboros.json`), oder hier
wurde schon eine Erlaubnis gemerkt (`.git/ouroboros.json`):

1. trägt er das Repo ins Register ein, damit `agent-usage` es mitmisst,
2. legt den Loop-Vertrag (`docs/loop.md`) in den Session-Kontext, dazu, was hier erlaubt,
   verboten und noch offen ist,
3. meldet Roadmap-Stand und Hausstil, wenn das Repo den Loop trägt, und den Agent-Zuschnitt.

Im Quell-Repo des Plugins meldet er nur den Agent-Zuschnitt: dort arbeitet der Agent-Designer.
Überall sonst bleibt er still. Er bricht nie eine Session ab, Exit ist immer 0.
"""

import json
import sys

import loopcfg


def run_check(name, check):
    try:
        return check()
    except Exception as error:  # ein kaputter Prüfer darf die anderen nicht mitnehmen
        print(f"{name}: übersprungen ({error})", file=sys.stderr)
        return ""


def roadmap(root):
    import roadmap_status
    findings, revisits = roadmap_status.check(root, "main", False)
    return roadmap_status.report(findings, revisits) if findings or revisits else ""


def docstyle(root):
    import docstyle as style
    findings = style.check(root)
    return style.report(findings, compact=True) if findings else ""


def agents(root):
    import agent_usage
    findings = agent_usage.measure(root, budget=agent_usage.HOOK_BUDGET_SECONDS)[5]
    return agent_usage.report(findings, compact=True) if findings else ""


def permission_summary(root):
    decided = loopcfg.permissions(root)
    lines = ["## Permissions in this repo (`loop-doc permissions`)", ""]
    for answer, label in (("yes", "allowed"), ("no", "denied"), (None, "open — ask once")):
        kinds = [kind for kind, value in decided.items() if value == answer]
        if kinds:
            lines.append(f"- {label}: {', '.join(kinds)}")
    return "\n".join(lines)


def main():
    root = loopcfg.project_root()
    active = loopcfg.is_active(root)
    source = loopcfg.plugin_source()
    at_source = source is not None and loopcfg.same_path(loopcfg.main_checkout(root), source)
    if not active and not at_source:
        return 0

    context, reports = [], []
    if active:
        loopcfg.register(root)
        context.append((loopcfg.PLUGIN_ROOT / "docs" / "loop.md").read_text(encoding="utf-8"))
        context.append(permission_summary(root))
        # Roadmap und Hausstil sind Konventionen eines Repos, das den Loop selbst trägt. In einem
        # fremden Repo wären sie Lärm über fremde Doku.
        if loopcfg.carries_loop(root):
            reports.append(run_check("roadmap-status", lambda: roadmap(root)))
            reports.append(run_check("docstyle", lambda: docstyle(root)))
    reports.append(run_check("agent-usage", lambda: agents(root)))
    reports = [r for r in reports if r]

    output = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                     "additionalContext": "\n\n".join(context + reports)}}
    if reports:
        output["systemMessage"] = "\n\n".join(reports)
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
