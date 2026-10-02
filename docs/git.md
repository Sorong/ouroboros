# Git

## Branch names

`<typ>/<kebab-slug>` — the slug is a topic, in the language the repo writes in (its CLAUDE.md or its
history), not an issue number: `feat/cart-discounts`,
`docs/adr-session-length`. The PR body carries the
`Closes #<n>` reference, so the branch doesn't have to.

| Typ        | For                                        |
| ---------- | ------------------------------------------ |
| `feat`     | new behaviour                              |
| `fix`      | a defect in shipped behaviour              |
| `refactor` | same behaviour, different structure        |
| `docs`     | roadmap, ADRs, `CONTEXT.md`, agent docs    |
| `chore`    | tooling, config, repo housekeeping         |

Older branches may use `feature/` — `feat/` is the current form; don't revive the long one.

## Commit messages

Only in a repo with a roadmap: a commit that implements part of a milestone step names the step
up front. Elsewhere the repo's own commit convention holds.

```
M2.3 Apply discounts in the shopping cart
```

`M<N>.<k> <subject>`, where `N` is the milestone and `k` the step in `docs/roadmap/m<N>.md`.
This prefix is the only thing that tells a *built* step from a *documented* one:
`roadmap-status` reads it off `main` and reports steps that have landed but carry no
tick. Without it, a merged step is invisible to everything except a human who remembers.

Commits belonging to no step — tooling, ADRs, repo housekeeping — carry no prefix.

## Worktrees

A Developer run works in its own worktree (the `ouroboros:developer` agent). Name the worktree
directory after the slug alone and the branch by the full convention:

```
git worktree add .claude/worktrees/<slug> -b <typ>/<slug> origin/main
```

then enter it with `EnterWorktree` (`path`). Creating it with `EnterWorktree` (`name`) instead
lets the tool derive the branch name, which doesn't follow the convention above.

Then prepare it as the repo's CLAUDE.md says, if a fresh worktree needs anything before it
builds. A repo whose worktree needs nothing has none.
