# Permissions

Code on a branch is always allowed — that is the work. Everything else the loop could leave in a
repo is asked once, and the answer is remembered.

## What is asked

| Kind | What it covers |
| --- | --- |
| `push` | pushing the branch to the remote |
| `pr` | opening a pull request |
| `issues` | creating issues and commenting on them |
| `labels` | creating and changing labels, including the loop's label set |
| `pr-comments` | replies in a PR, e.g. the Product Owner's `Zuordnung:` |
| `adr` | files under `docs/adr/` |
| `context` | `CONTEXT.md` |
| `roadmap` | `docs/roadmap.md`, `docs/roadmap/` |
| `principles` | `docs/code-principles.md` |

`loop-permission` prints what is decided for the current repo. Every kind nobody has answered
is open.

## Ask once, then remember

Before the first write of an open kind, the role stops and asks the stakeholder — one question,
the kind and what it is about to write. Ask everything the current unit will need in one go.
Then, before acting, write the answer down:

```
loop-permission adr no
```

The answer lands in `.git/ouroboros.json` of the clone. Git never tracks what lies inside
`.git`, so the repo stays untouched, and every worktree of the clone sees the same answers.
Another clone, on another machine, asks once more. Never ask for a kind that is decided, and never
write a kind that is `no`.

A repo that carries the loop itself decides for everyone in `.claude/ouroboros.json`:

```json
{ "permissions": { "*": "yes" } }
```

`"*"` stands for every kind; a named kind overrides it. What the repo decides, nobody is asked.

## Where a `no` sends it

The work still gets done; only its record moves:

| Denied | The record goes to |
| --- | --- |
| `adr`, `context`, `principles` | the PR body, as a "Decisions" section; with `pr` denied too, the stakeholder in the session |
| `issues` | the session: a stop is reported to whoever spawned the role, a cut stays a list in the session |
| `labels` | a comment naming the state (`needs-refinement`, …) if `issues` allows it, else the session |
| `pr-comments` | `loop-note` — the attribution lands in `~/.claude/ouroboros/`, where `agent-usage` counts it like a PR reply |
| `roadmap` | nothing: without a roadmap, work comes as issues or orders |
| `push`, `pr` | the branch stays local, and the stakeholder gets its name |
