# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on an external reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |
| _(extra, not in mattpocock/skills)_ | `needs-refinement` | Developer stopped mid-issue on a WAS question — see `ouroboros:architect`. Distinct from `needs-info`: nobody external is waiting, an agent is. |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Issues the Product Owner creates itself (see `ouroboros:product-owner`) start directly at
`ready-for-agent` — they skip `needs-triage`, since the Product Owner already groomed them at
creation time. `needs-triage` stays for anything that didn't come out of the delivery loop (an
ad-hoc bug note, an unplanned idea).

Edit the right-hand column to match whatever vocabulary you actually use.

## `revisit:<trigger>` — when a parked issue comes back

Triage can end in "not now, but not never" (see `ouroboros:triage`). Such an issue keeps
`needs-triage` — it is still undecided work — and gains a second label naming *when* to look at
it again. Same `prefix:value` shape as the `wayfinder:` labels in `loop-doc issue-tracker`.

| Form | Means | Example |
| ---- | ----- | ------- |
| `revisit:m<N>` | when milestone N is reached | `revisit:m5` |
| `revisit:m<N>.<k>` | when step k of milestone N is next | `revisit:m2.6` |
| `revisit:<work>` | when a named piece of work happens | `revisit:adr-0011` |

**Every parked issue carries at least one milestone-shaped trigger.** Only those can be made due
automatically: `roadmap-status` compares them against the roadmap and reports the ones
that have come around, via the `SessionStart` hook. A free-form trigger has no timer — it records
the real reason, which is often work that isn't scheduled yet, and it pairs with a
milestone-shaped backstop so the issue can't disappear if that work keeps slipping.

Name the *earliest* point at which the issue is worth another look, not the point at which it
would be implemented.
