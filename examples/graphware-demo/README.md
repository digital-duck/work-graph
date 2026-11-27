# graphware demo: a plant waterer

A small product that mixes hardware and software, to show work-graph's `design` area (`idea -> spec -> design -> build -> test -> release | integrate`).

| Step | What is here |
|---|---|
| idea | `docs/ideas/IDEA-001.md`, `IDEA-002.md` |
| spec | `docs/specs/SPEC-001.md`, `SPEC-002.md` (`refines:` an idea) |
| design | `design/plant-waterer.arch.yaml`, an architecture graph; components list `satisfies: [SPEC-001]` |
| build | `src/*.py` (`# implements: <component>`) and `hardware/bom.md` (`implements: [moisture-sensor, pump]`) |
| test | `tests/test_firmware.py` (`# verifies: SPEC-001`, `# verifies: firmware`) |

It has **deliberate gaps**, which the design area reports (the demo's test pins them):

```bash
workgraph gaps -c examples/graphware-demo/workspace.yaml
```

- `idea has no spec`: IDEA-002
- `spec has no design`: SPEC-002 (no component satisfies it)
- `spec has no test`: SPEC-002
- `component has no build artifact`: app (it is only planned)
- `component has no test`: app, api, moisture sensor, pump

Close a gap, and it disappears from the list: write a design for SPEC-002, add `# verifies: app` to a test, and so on.

The architecture file is also a picture and a checkable contract (GraphLang's `graf util`):

```bash
graf util arch2mmd design/plant-waterer.arch.yaml      # -> plant-waterer.mmd (a Mermaid chart)
graf util arch2mmd design/plant-waterer.arch.yaml --verify   # arch -> mmd -> arch is lossless
```
