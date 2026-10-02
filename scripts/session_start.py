#!/usr/bin/env python3
"""The plugin's SessionStart hook.

In a repo where the loop runs — it carries it (`.claude/ouroboros.json`), or a permission was
already remembered here (`.git/ouroboros.json`) — it:

1. enters the repo in the registry, so `agent-usage` measures it too,
2. puts the loop contract (`docs/loop.md`) into the session context, along with what is
   allowed, denied and still open here,
3. reports roadmap state and house style if the repo carries the loop, and the agent cut.

In the plugin's source repo it reports only the agent cut: that is where the Agent-Designer
works. Everywhere else it stays silent. It never aborts a session; the exit is always 0.
"""

import json
import sys

import loopcfg


def run_check(name, check):
    try:
        return check()
    except Exception as error:  # a broken check must not take the others down with it
        print(f"{name}: skipped ({error})", file=sys.stderr)
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
        # Roadmap and house style are conventions of a repo that carries the loop itself. In a
        # foreign repo they would be noise about foreign docs.

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
