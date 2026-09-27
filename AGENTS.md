# gk-forge — agent guide

Content generation: seedsmith and the `tools/*Gen` family. **Public.**

The binding rules for every Keepverse repository are in the workspace root:
`../AGENTS.md` (loaded automatically for any agent working inside this folder).
Docs live in `../docs/`. This file is emitted by kvsplit; change its template in
`tools/kvsplit/rules/templates/`, not here.

## Rules specific to this repo

- **Generated seed data is never hand-edited.** A file carrying `_meta.model` /
  `promptVersion` / `batch` provenance is this repo's tools' output. Fix the tool,
  regenerate, commit the diff. Editing the file forks the corpus from its
  generator: the next run reverts you, the ledger stops describing the file, and
  the defect is invisible to every other consumer.
  Author by hand only where the shape says content is authored: `**/_registry/**`,
  `**/_exemplars/**`, and hand-authored kinds.
- **`data/tuning/**` is never hand-edited in place.** It belongs to `gk-core` and
  is published as `v{n+1}` through the publish tool.
- **Every generator has a `--check` mode and CI runs it.** A generator that
  cannot reproduce its own output byte-identically is a defect. The committed
  corpus is the contract.
- **No LLM inside a generator.** Models author identity only — names, flavour,
  atom-family picks. Every magnitude is table-owned. Nondeterminism belongs to the
  agent reconcile step, never to the tool.
- **A tool lives where its output's owner lives.** Generator code → here.
  Code emitting `src/**` → `gk-core`. Live-game tools → `gk-fusion`.
- **Fix the generator when a seed test fails** — never edit the emitted JSON to
  turn a test green. A failing seed test is a stale test or a generator defect.

## Build and test

```bash
python -m pip install -r requirements.lock
python -m seedsmith check data/seed/items --adapter items
python -m pytest tests/ -q
```

## Status

Empty; not staged yet. The ownership rule for this repo exists but `apply` has not
run.
