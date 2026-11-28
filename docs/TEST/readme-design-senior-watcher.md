# The senior-watcher design demo: what was added, and how to verify it

Written 2026-11-26 for review. Everything below was run once by the author of the change; the outputs shown are what that run printed. Nothing is committed yet. It is the second demo of the `design` area (`src/workgraph/areas/design.yaml`), after the plant waterer (`readme-design-plant-waterer.md`), and it needed **no code change**: the `satisfies:` support added for the first demo is enough.

## 1. What this is

```
idea -> spec -> design -> build -> test -> release -> operate
```

A home-care product for a senior who lives alone, built from **old Android phones**:

- a **worn phone** (on a lanyard) detects a fall from its accelerometer and has an SOS long-press;
- a **room phone** per room (wall mount, on the charger) sees motion with its front camera and shows "Are you OK? Tap to cancel";
- a **hub phone** with a SIM runs the alert engine and calls / texts the family in order until someone answers.

Each phone runs a small Python app under Termux + Termux:API (`termux-sensor`, `termux-telephony-call`, `termux-sms-send`), talking to the hub over the home Wi-Fi. It is a private home, so privacy controls are out of scope by request. Like the plant waterer it has deliberate gaps, so the gap report has something to show.

Compared with the plant waterer it adds: one spec satisfied by several components (and one component satisfying several specs), a fourth layer, and **hardware tested by a manual checklist** (a markdown file under `tests/` whose frontmatter says `verifies: [hub-phone, wearable-phone]`).

## 2. What changed

| Path | Change |
|---|---|
| `examples/senior-watcher/` | **New.** The demo project (20 files, section 3). |
| `tests/test_senior_watcher_demo.py` | **New.** 4 tests that pin the demo (section 5). |
| `CLAUDE.md` | One sentence: the demo is among the examples whose gaps are deliberate. |

Not changed: `src/`, `examples/workspace.yaml` (the multi-area tests need exactly two areas there, so the demo has its own `workspace.yaml`), the plant-waterer demo.

## 3. The demo project

```
examples/senior-watcher/
  workspace.yaml                       area: design, one project "senior-watcher"
  README.md                            the demo's own description
  docs/ideas/IDEA-001.md               Get help fast when Mom falls
  docs/ideas/IDEA-002.md               Notice a day that is too quiet
  docs/ideas/IDEA-003.md               Remind Mom to take her pills                 (no spec: gap)
  docs/specs/SPEC-001.md               Detect a fall and call the family            refines: [IDEA-001]
  docs/specs/SPEC-002.md               SOS button calls at once                     refines: [IDEA-001]
  docs/specs/SPEC-003.md               Alert after four quiet daytime hours         refines: [IDEA-002]   (no test: gap)
  docs/specs/SPEC-004.md               Family can see the last 24 hours             refines: [IDEA-002]   (no test: gap)
  docs/specs/SPEC-005.md               A silent phone is an alert too (watchdog)    refines: [IDEA-001]   (no design, no test: gaps)
  design/senior-watcher.arch.yaml      the architecture graph (8 components, 4 layers)
  hardware/bom.md                      implements: [hub-phone, wearable-phone, room-phone]
  src/alert_engine.py                  # implements: alert-engine   (cancel window, escalation, inactivity timer)
  src/dialer.py                        # implements: dialer         (call contacts in order, SMS; Termux:API)
  src/wearable.py                      # implements: wearable-app   (fall = impact > 2.5 g then 20 s still; SOS)
  src/room_monitor.py                  # implements: room-monitor   (frame-difference motion)
  tests/test_fall.py                   # verifies: SPEC-001, wearable-app
  tests/test_alert_engine.py           # verifies: SPEC-001, SPEC-002, alert-engine
  tests/test_dialer.py                 # verifies: dialer
  tests/hardware/bench-checklist.md    verifies: [hub-phone, wearable-phone]   (manual; room phone not covered: gap)
```

The architecture (`rules: edges_point_down, requires_acyclic`):

| Layer (rank) | Components | Status |
|---|---|---|
| Family (4) | `caregiver-view` (satisfies SPEC-004) | planned |
| Hub (3) | `alert-engine` (SPEC-001, 002, 003) | validated |
| Phone apps (2) | `dialer` (001, 002), `wearable-app` (001, 002), `room-monitor` (003) | prototype |
| Reused phones (1) | `hub-phone`, `wearable-phone` (name "worn phone"), `room-phone` | unrated |

Edges: `caregiver-view -> alert-engine` (network, Wi-Fi); `alert-engine -> dialer`; `alert-engine -> wearable-app` and `-> room-monitor` (network, Wi-Fi); each app -> its phone.

## 4. How to verify

Run from `work-graph/`.

### 4.1 The gap report

```bash
WORKGRAPH_HOME=/tmp/wgdemo workgraph gaps -c examples/senior-watcher/workspace.yaml -q
```

Expected (this is what was printed):

```
[design] component has no build artifact (add `# implements: <component id>` in its code) (1)
  - caregiver view  (senior-watcher:design/senior-watcher.arch.yaml)

[design] component has no test (3)
  - caregiver view  (senior-watcher:design/senior-watcher.arch.yaml)
  - room monitor  (senior-watcher:design/senior-watcher.arch.yaml)
  - room phone  (senior-watcher:design/senior-watcher.arch.yaml)

[design] idea has no spec (1)
  - IDEA-003: Remind Mom to take her pills  (senior-watcher:docs/ideas/IDEA-003.md)

[design] spec has no design (1)
  - SPEC-005: A silent phone is an alert too  (senior-watcher:docs/specs/SPEC-005.md)

[design] spec has no test (3)
  - SPEC-003: Alert after four quiet daytime hours  (senior-watcher:docs/specs/SPEC-003.md)
  - SPEC-004: Family can see the last 24 hours  (senior-watcher:docs/specs/SPEC-004.md)
  - SPEC-005: A silent phone is an alert too  (senior-watcher:docs/specs/SPEC-005.md)

9 gaps, 0 warnings
```

Check that: **9 gaps, 0 warnings**; `hub phone` and `worn phone` are not under "has no test" (the bench checklist covers them) while `room phone` is; no phone is under "has no build artifact" (the BOM covers all three). SPEC-005 is the instructive gap: the product's safety depends on noticing a watcher phone that died quietly, and nothing is designed for it yet.

### 4.2 The gaps close when you fix them

Each row was tried on a scratch copy of the demo (`cp -r examples/senior-watcher <scratch>`), then the copy was discarded.

| Do this | Result (observed) |
|---|---|
| add `tests/test_room_monitor.py` with `# verifies: room-monitor` and `# verifies: SPEC-003` | 2 gaps gone; **7 gaps** |
| add `room-phone` to the checklist's `verifies:` | **8 gaps** |
| add `SPEC-005` to `alert-engine`'s `satisfies:` | `spec has no design` disappears; **8 gaps** |
| add `docs/specs/SPEC-006.md` with `refines: [IDEA-003]` | `idea has no spec` disappears, **but 10 gaps**: SPEC-006 has no design and no test yet |
| add a typo `SPEC-099` to `caregiver-view`'s `satisfies:` | **9 gaps, 1 warning**: ``broken reference `satisfies: SPEC-099` `` |

### 4.3 The tests

```bash
python -m pytest tests/test_senior_watcher_demo.py -q    # 4 passed
python -m pytest tests -q
```

The whole suite, in the shell used here: **132 passed, 1 skipped** (128 passed before the 4 new tests). The skip is `tests/test_ui.py` ("pandas/pyarrow unusable in this environment"): that shell was conda `base`, not `graf`. Re-run in `graf` to confirm the UI tests too.

### 4.4 The architecture file with GraphLang's tools

```bash
cd examples/senior-watcher
graf util arch2mmd design/senior-watcher.arch.yaml --check     # printed: OK: design/senior-watcher.arch.yaml
graf util arch2mmd design/senior-watcher.arch.yaml --verify    # printed: OK: ... -> mmd -> arch is identical
```

`graf util arch2mmd design/senior-watcher.arch.yaml` (without a flag) writes `senior-watcher.mmd`; not generated for this review.

### 4.5 The demo's own tests

```bash
cd examples/senior-watcher
python -m pytest tests -c /dev/null --rootdir=.     # 7 passed
```

The code is pure logic plus thin Termux wrappers (`termux_call`, `termux_sms`) that the tests replace, so it runs on a desktop; on a phone the same modules run under Termux.

## 5. What the new tests pin

| Test | What it asserts |
|---|---|
| `test_the_demo_has_exactly_the_gaps_its_readme_lists` | The 9 gaps of 4.1, and no warnings. |
| `test_the_fall_chain_is_linked_idea_to_spec_to_design_to_build_to_test` | `SPEC-001 refines IDEA-001`; `alert engine` and `wearable app` satisfy SPEC-001; `alert_engine.py implements alert engine`; `test_fall.py verifies SPEC-001`; `test_alert_engine.py verifies SPEC-002`. |
| `test_hardware_is_built_by_the_bom_and_tested_by_a_manual_checklist` | Every phone has an `implements` edge; hub and worn phone have a `verifies` edge; the room phone has none. |
| `test_the_architecture_file_is_valid_for_graflangs_tools` | No validation errors **or warnings**, and the arch -> mmd -> arch round trip holds. Skipped without graflang. |

Edit the demo and the README and this test together.

## 6. Known limits and open points

- Invented example; the thresholds (2.5 g, 20 s, 4 h, 15 min) are plausible defaults, not clinically validated. The code is a demo, not a medical or emergency device, and it does not call emergency services.
- Not exercised: `release` / `integrate` stages (no CHANGELOG or install script yet); a natural next step is `release/install.md` with `ships: [...]`.
- The manual checklist counts as a test because the gap rule only asks for an incoming `verifies` edge; nothing checks that its boxes are ticked.
- Not verified: `workgraph ui` and `workgraph viz` on this demo.
