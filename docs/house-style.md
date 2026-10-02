# House style for decision documents

Applies to the documents that carry decisions: `docs/roadmap.md`, `docs/roadmap/m<N>.md`, ADRs
from the number `.claude/ouroboros.json` names on, and `CONTEXT.md` outside its translation table. Two rules,
both with the same reason: the Developer reads a spec text as an instruction.

## Name decisions, not code

A step, an ADR or an `Ergebnis:` paragraph points at its ADRs and uses the terms from
`CONTEXT.md`. Type, method and field names of this repo don't appear, not even in backticks.

- An identifier for unbuilt code is a prediction the Developer reads as an instruction.
- A later rename leaves it wrong in a file nobody edits. ADRs have a supersede protocol and
  `CONTEXT.md` has the translation table, a roadmap line has neither. It only ages.
- What a decision demands of the code becomes a rule in `docs/code-principles.md`. What a term
  is called in code is the table in `CONTEXT.md`. Both move with the code.

Backticks stay for file paths and the fields of the ADR format. Issue and PR numbers are fine,
both are traceable. Vocabulary from outside the repo (an engine, a framework) is a word, not an
identifier — `.claude/ouroboros.json` lists it so the check doesn't flag it.

## One thought per sentence

At most 30 words, at most one dash, no semicolon. Reason, restriction and contrast each get a
sentence of their own. What hangs off a main clause is read as part of its instruction, or not
at all.

## The check

The `SessionStart` hook runs both rules and reports violations: `docstyle` for ADRs and
`CONTEXT.md`, `roadmap-status` for the roadmap files. Run either by hand for the full list.
What the check cannot see — whether a sentence carries one thought — stays the writer's.

Per repo, in `.claude/ouroboros.json`:

```json
{
  "docstyle": {
    "adrSectionsFrom": 1,
    "adrProseFrom": 1,
    "adrSections": ["Kontext", "Optionen", "Entscheidung", "Konsequenzen"],
    "foreignNames": ["MonoBehaviour"]
  }
}
```

`adrSectionsFrom` and `adrProseFrom` let a repo keep ADRs written before it adopted the rules:
older ones are not rewritten. Every key is optional.
