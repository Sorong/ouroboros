# Roadmap conventions

The shape `roadmap-status` reads. A repo that runs the loop keeps its plan in this shape, so a
merged step, a parked issue and a stale counter all become visible without anyone remembering.

The roadmap is written in the repo's language. The few fixed words below have an English and a
German form, and the check reads both: keep the one the roadmap already uses.

| English | German |
| --- | --- |
| `## Next concrete step` | `## Nächster konkreter Schritt` |
| `M<N> step <k>` | `M<N> Schritt <k>` |
| `open (k/n)` | `offen (k/n)` |
| `k/n steps` | `k/n Schritte` |
| `Result:` | `Ergebnis:` |

## Files

- `docs/roadmap.md` — the overview: principles, the milestone table, the next concrete step.
  The Project Manager owns it.
- `docs/roadmap/m<N>.md` — one file per milestone that is broken down into steps. The Product
  Owner owns it, the Architect writes each step's spec into it at the concept stage.
- `README.md` — optional progress display, derived from the ticks.

## Milestone table in `docs/roadmap.md`

One row per milestone, first cell `M<N>`, status in the fifth column (counting the empty cell
before the first `|`):

```
| # | Milestone | … | Status | Details |
|---|---|---|---|---|
| M2 | Shopping cart | … | open (4/10) | [roadmap/m2.md](roadmap/m2.md) |
```

The counter `k/n` is derived from the ticks in `m<N>.md`. `✅` in the cell marks a milestone done.

## Next concrete step

A section `## Next concrete step` in `docs/roadmap.md` naming `M<N> step <k>`. The
check reports it as stale once that step is ticked or has commits on `main`.

## Steps in `docs/roadmap/m<N>.md`

A numbered list, one step per item. A done step carries `✅` right after its number:

```
3. ✅ Apply discounts in the shopping cart …
4. Redeem vouchers …
```

The step text is the spec the concept stage wrote. The close-out appends a `Result:`
paragraph underneath it. Both follow `loop-doc house-style`.

## README progress (optional)

A table with `M<N>` rows whose fourth column holds a bar of `█`/`░` and `k/n steps`. The
check compares both against the ticks.

## What ties it to `main`

- The commit prefix `M<N>.<k>` (`loop-doc git`) tells a built step from a documented one.
- The labels `revisit:m<N>` and `revisit:m<N>.<k>` (`loop-doc triage-labels`) make a parked
  issue due once the roadmap reaches its trigger.

A repo without `docs/roadmap.md` is not checked. Nothing else in the loop needs the roadmap to
exist before the first milestone is written.
