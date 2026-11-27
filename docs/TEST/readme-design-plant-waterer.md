# The `design` area demo: what was added, and how to verify it

Written 2026-11-27 for review. Everything below was run once by the author of the change; the outputs shown are what that run printed. Nothing is committed yet.

## 1. What this is

work-graph has a `design` area pack (`src/workgraph/areas/design.yaml`): the prototype of the graphware cycle

```
idea -> spec -> design -> build -> test -> release | integrate
```

This change adds a **demo project** for that pack, `examples/graphware-demo/`, and one small processor feature it needs. The demo is a plant waterer (a moisture sensor, a pump, firmware, a cloud API and a phone app), chosen because it mixes hardware and software. It has deliberate gaps, like `acme-shop` and `rq-demo`, so that the gap report has something to show.

## 2. What changed

| Path | Change |
|---|---|
| `examples/graphware-demo/` | **New.** The demo project (11 files, listed in section 3). |
| `src/workgraph/processors.py` | `p_arch` (the `arch` processor) now reads `satisfies: [SPEC-1]` on a component and emits a `satisfies` edge from that component to the spec. Without it, nothing could link a design to a spec. |
| `tests/test_design_demo.py` | **New.** 3 tests that pin the demo (section 6). |
| `CLAUDE.md` | One sentence: the demo is among the examples whose gaps are deliberate, and why it has its own `workspace.yaml`. |

Not changed on purpose: `examples/workspace.yaml`. Existing tests (`tests/test_pipeline.py::test_multi_area_workspace_gaps`) expect exactly two areas there (`sdlc`, `research`), so the demo has its own workspace file.

## 3. The demo project

```
examples/graphware-demo/
  workspace.yaml                      area: design, one project "plant-waterer"
  README.md                           the demo's own description
  docs/ideas/IDEA-001.md              Plants should water themselves
  docs/ideas/IDEA-002.md              Tell me when the tank is empty        (no spec: a deliberate gap)
  docs/specs/SPEC-001.md              Water when the soil is dry            refines: [IDEA-001]
  docs/specs/SPEC-002.md              Show the moisture history in the app  refines: [IDEA-001]   (no design, no test: gaps)
  design/plant-waterer.arch.yaml      the architecture graph (5 components)
  hardware/bom.md                     bill of materials, implements: [moisture-sensor, pump]
  src/firmware.py                     # implements: firmware
  src/api.py                          # implements: api
  tests/test_firmware.py              # verifies: SPEC-001  and  # verifies: firmware
```

How each step of the cycle is represented:

| Step | Artifact | How it is linked |
|---|---|---|
| idea | `docs/ideas/*.md` | frontmatter `kind: idea`; tagged by path (`**/ideas/**`) |
| spec | `docs/specs/*.md` | frontmatter `kind: spec`, `refines: [IDEA-001]` |
| design | `design/plant-waterer.arch.yaml` | components, each `satisfies: [SPEC-001]` (new, see section 2) |
| build (software) | `src/*.py` | a comment `# implements: <component id>` |
| build (hardware) | `hardware/bom.md` | frontmatter `implements: [moisture-sensor, pump]`: parts are "built" by a bill of materials, not code |
| test | `tests/test_firmware.py` | comments `# verifies: SPEC-001` and `# verifies: firmware` |

The architecture file has three layers (App, Cloud, Device), five components (`app`, `api`, `firmware`, `moisture-sensor`, `pump`) and four edges: `app -> api`, `api -> firmware` (kind `network`, label `MQTT`), `firmware -> moisture-sensor`, `firmware -> pump`. Statuses: `app` is `planned`, `firmware` is `validated`, `pump` is `prototype`, the others are unrated. Its rules are `edges_point_down` and `requires_acyclic`.

## 4. How to verify

Run these from `work-graph/` in the environment that has work-graph, graflang and pytest (the `graf` conda env was used).

### 4.1 The gap report (the main check)

```bash
WORKGRAPH_HOME=/tmp/wgdemo workgraph gaps -c examples/graphware-demo/workspace.yaml -q
```

`WORKGRAPH_HOME` points work-graph's home folder at a scratch folder, so the run does not write to your real `~/workgraph`. `-q` hides the progress lines. Expected output (this is what was printed):

```
[design] component has no build artifact (add `# implements: <component id>` in its code) (1)
  - app  (plant-waterer:design/plant-waterer.arch.yaml)

[design] component has no test (4)
  - api  (plant-waterer:design/plant-waterer.arch.yaml)
  - app  (plant-waterer:design/plant-waterer.arch.yaml)
  - moisture sensor  (plant-waterer:design/plant-waterer.arch.yaml)
  - pump  (plant-waterer:design/plant-waterer.arch.yaml)

[design] idea has no spec (1)
  - IDEA-002: Tell me when the tank is empty  (plant-waterer:docs/ideas/IDEA-002.md)

[design] spec has no design (1)
  - SPEC-002: Show the moisture history in the app  (plant-waterer:docs/specs/SPEC-002.md)

[design] spec has no test (1)
  - SPEC-002: Show the moisture history in the app  (plant-waterer:docs/specs/SPEC-002.md)

8 gaps, 0 warnings
```

Check that:
- there are **8 gaps and 0 warnings** (a warning would mean the architecture file broke one of its own rules, or a reference does not resolve);
- `firmware` and `SPEC-001` are **not** listed: they are fully covered (a design, code, a test, and a `satisfies` link);
- `moisture sensor` and `pump` are **not** in "has no build artifact": the bill of materials covers them.

### 4.2 The gaps close when you fix them

Each row was tried on a scratch copy of the demo. Make the change, re-run 4.1, check the result, then undo the change.

| Do this | Result (observed) |
|---|---|
| add `# verifies: app` as a first line of `tests/test_firmware.py` | `component has no test` drops from 4 to 3 (`app` gone); **7 gaps** |
| add `satisfies: [SPEC-002]` to the `app` component in `design/plant-waterer.arch.yaml` | `spec has no design` disappears (SPEC-002 is now designed); **7 gaps** |
| create `src/app.py` containing `# implements: app` and any code | `component has no build artifact` disappears; **7 gaps** |
| add `docs/specs/SPEC-003.md` with `kind: spec` and `refines: [IDEA-002]` | `idea has no spec` disappears, **but 9 gaps**: the new SPEC-003 has no design and no test yet. Closing a gap at one step exposes the next. |

### 4.3 The tests

```bash
python -m pytest tests/test_design_demo.py tests/test_arch_processor.py -q
python -m pytest tests -q
```

Expected: `7 passed` for the first command; `132 passed` for the whole suite (it was 129 before the 3 new tests).

### 4.4 The architecture file with GraphLang's tools

These use `graf` (graflang), which is a separate package:

```bash
cd examples/graphware-demo
graf util arch2mmd design/plant-waterer.arch.yaml --check     # expect: OK: design/plant-waterer.arch.yaml
graf util arch2mmd design/plant-waterer.arch.yaml --verify    # expect: OK: ... -> mmd -> arch is identical
```

To see the picture, `graf util arch2mmd design/plant-waterer.arch.yaml` writes `plant-waterer.mmd` (Mermaid) next to the input. It was not generated for this review, so you will see it for the first time. That is a new file in the demo folder, so delete it afterwards if you do not want to keep it.

### 4.5 The demo's own tests (optional)

`tests/test_firmware.py` in the demo is a real pytest file. work-graph's own suite never runs it (its `testpaths` is the top-level `tests/`); work-graph only reads it as text to find the `# verifies:` comments. To run it:

```bash
cd examples/graphware-demo
python -m pytest tests/test_firmware.py -c /dev/null --rootdir=.
```

Expected: `2 passed`. The `-c /dev/null --rootdir=.` matters: without it pytest finds work-graph's own `pyproject.toml` above the demo and applies that configuration instead (one run without it reported "No tests collected").

## 5. The one code change, in detail

In `src/workgraph/processors.py`, `p_arch` loops over the components of each `*.arch.yaml`. After it emits the `contains` edge it now also does:

```python
for spec in n.get("satisfies") or []:
    out["refs"].append({"source": ("id", nid), "relation": "satisfies", "target": str(spec), "file": rel})
```

The target is resolved like any other reference (by the spec's `doc_id`, here `SPEC-001`). A `satisfies` target that matches nothing becomes a `broken reference` warning, the same as a bad `refines:` in frontmatter. The `design` pack's expectation `spec has no design` is satisfied by an incoming `satisfies` edge, which is what this produces.

Verified the other way round: with every `satisfies:` removed from the demo's architecture file, `SPEC-001` joins SPEC-002 under `spec has no design` (2 specs listed).

## 6. What the new tests pin

`tests/test_design_demo.py`:

| Test | What it asserts |
|---|---|
| `test_the_demo_has_exactly_the_gaps_its_readme_lists` | The set of 8 gaps from 4.1, and an empty warnings list. |
| `test_the_whole_chain_is_linked_idea_to_spec_to_design_to_build_to_test` | `SPEC-001 refines IDEA-001`; `firmware satisfies SPEC-001`; `firmware.py implements firmware`; the bill of materials implements `pump` and `moisture sensor`; `test_firmware.py verifies SPEC-001` and `verifies firmware`. |
| `test_the_architecture_file_is_valid_for_graflangs_tools` | The architecture file validates and survives the arch -> mmd -> arch round trip. Skipped if graflang is not importable. |

If someone edits the demo and a gap appears or disappears, the first test fails and says which. Update the test and the demo's README together.

## 7. Known limits and open points

- The plant waterer is an invented example, not anything from your stack. If you want the demo to use a real product of yours, only the files under `examples/graphware-demo/` change.
- The `arch` processor has no check that a `satisfies` target is a spec. It resolves any id (a requirement, an idea). That is consistent with how frontmatter references work, but it is not enforced.
- Component ids become `doc_id`s, so they must be unique across all `*.arch.yaml` files in one project. The demo has one architecture file, so this is not exercised.
- Component labels come from the `name` field, so `moisture-sensor` (id) is shown as `moisture sensor` (name) in the gap report.
- Not verified: the Streamlit UI (`workgraph ui`) and `workgraph viz` were not run on the demo.

## 8. Related changes made in the same session

These are separate from the demo but live in the same repo, so you will see them in `git status`:

- `tests/test_home_and_claude.py` and `tests/test_ui.py`: three tests had hard-coded node counts (31 and 70) that no longer matched the example project (26). They now take the count from the built graph. This is what moved the suite from 126 passed and 3 failed to 129 passed.
- `src/workgraph/areas/design.yaml`, `p_arch` and `tests/test_arch_processor.py` were added earlier, in the session that created the `design` area.
