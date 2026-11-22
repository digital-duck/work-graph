# Changelog

## Unreleased (0.3.0)

**Renamed, to keep each word for one thing** (plan: `docs/DEV/graflang-refactor.md`). Run `workgraph utils migrate` once on an existing home; `--dry-run` shows what it would do.

- **`domain` is now `area`**: the vocabulary and processing pack of a project (`sdlc`, `research`, `publishing`). `domain:` -> `area:` in `workspace.yaml` and in your own packs, `custom/domains/` -> `custom/areas/`, `workgraph utils domains` -> `utils areas`, `--domain` -> `--area`, the node field `domain` -> `area`, `src/workgraph/domains/` -> `areas/`.
- **`layer` is now `domain`**: the org, product, process and repo graphs. `layer:` -> `domain:` in graph files (`schema: workgraph/2`), the node field `layer` -> `domain`, `workgraph utils layers` -> `utils domains` (the domain map), `viz --layer` -> `--domain`, `<out>/layers/` -> `<out>/domains/`, the Layers tab -> Domains. The database columns are renamed on open.
- **Compatibility, for this release only:** the loader reads the old keys (`domain:` in workspace files and packs, `layer:` and `schema: workgraph/1` in graph files) with a warning; `init_home` moves `custom/domains/`; a `graph.json` built by 0.2.x is refused with "run `workgraph build` again" (it carries no `workgraph_format`).
- `workgraph utils migrate`: the one command that rewrites the old files and folders (safe to run twice).
- Careful: `workgraph utils domains` used to list the packs; it now shows the domain map. The packs are `utils areas`.

## 0.2.0

- `workgraph viz` draws through [zinet](https://pypi.org/project/zinet/) (>=0.2.0): the same engines as GraphLang (`cytoscape`, `graphviz`, `mermaid`, `ascii`, and `pyvis` / `graphify`), hover highlighting on the interactive page; the Map tab uses the same page. `viz.py` is now a style plus selection rules.
- `convert.py` uses zinet's comment-preserving YAML (`zinet.roundtrip`) with workgraph's `nodes` / `edges` layout.
- New dependency: `zinet>=0.2.0`. The extra `viz` is now `zinet[pyvis]`.

## 0.1.0

First release.
