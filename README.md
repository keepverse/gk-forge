# gk-forge

Content generation: seedsmith and the `tools/*Gen` family. Every corpus the game
ships is produced by code in this repo.

- **Working rules:** [AGENTS.md](AGENTS.md)

## What belongs here

| Path | What it is |
|---|---|
| `seedsmith/` | The offline content pipeline and its adapters. |
| `tools/*Gen/` | `CreatureSpeciesGen`, `TreeBinder`, `FamilyExpandGen`, … |
| `tools/*Importer/` | Importers that turn a corpus into runtime state. |

**The placement rule: a tool lives where its output's owner lives.** Generator
code → `gk-forge` (its output → a data repo). Code that emits `src/**` →
`gk-core`. Live-game tools → `gk-fusion`.

## The rule that matters most

**Generated seed data is never hand-edited.** A file carrying
`_meta.model` / `promptVersion` / `batch` is a tool's output. Fix the tool,
regenerate, commit the diff. Editing the file forks the corpus from its
generator: the next run reverts you, the ledger stops describing the file, and
the bug is invisible to every other consumer.

Author by hand only where the shape says content is authored: registries,
exemplars, and hand-authored kinds.

## Determinism

Every generator has a `--check` mode, and CI runs it. A generator that cannot
reproduce its own output byte-identically is a defect, not a flake — the
committed corpus is the contract.

## Status

Empty. `kvsplit` has not staged seedsmith here yet; its ownership rule exists
(`tools/seedsmith/**` → `gk-forge`) but `apply` has not run.
