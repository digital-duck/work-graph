"""The `arch` processor and the `develop` area: an architecture graph becomes component nodes with edges, tagged `design`; gaps name the skipped steps."""
from workgraph.analyze import find_gaps
from workgraph.area import Workspace, validate_pack
from workgraph.pipeline import build_workspace

ARCH = """arch: 1
name: demo
title: Demo stack
rules: {edges_point_down: true, requires_acyclic: true}
layers:
  - {id: apps, rank: 2, title: Apps, nodes: [{id: shop, name: shop, summary: [the app]}]}
  - {id: libs, rank: 1, title: Libs, nodes: [{id: core, name: core, summary: [the core], pkg: core-lib, status: validated}, {id: extra, name: extra}]}
edges:
  - {from: shop, to: core}
  - {from: shop, to: extra, kind: optional}
"""
CODE = "# implements: core\ndef f():\n    return 1\n"
TEST = "# verifies: core\nfrom core import f\n\ndef test_f():\n    assert f() == 1\n"


def _build(tmp_path):
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    (p / "tests").mkdir()
    (p / "demo.arch.yaml").write_text(ARCH)
    (p / "src" / "core.py").write_text(CODE)
    (p / "tests" / "test_core.py").write_text(TEST)
    cfg = tmp_path / "workspace.yaml"
    cfg.write_text("area: develop\nprojects:\n  - {name: p, path: proj}\n")
    ws = Workspace.load(cfg)
    M, _, warnings = build_workspace(ws)
    return ws, M, warnings


def _edges(M, rel):
    return {(M.nodes[u].get("label"), M.nodes[v].get("label")) for u, v, d in M.edges(data=True) if d.get("relation") == rel}


def test_design_pack_is_valid():
    assert validate_pack("develop") == []


def test_components_edges_and_stage(tmp_path):
    _, M, warnings = _build(tmp_path)
    comps = {M.nodes[n]["label"]: n for n in M if M.nodes[n].get("kind") == "component"}
    assert set(comps) == {"shop", "core", "extra"}
    assert "design" in M.nodes[comps["core"]]["stages"] and M.nodes[comps["core"]]["status"] == "validated"
    assert _edges(M, "requires") == {("shop", "core")} and _edges(M, "optional") == {("shop", "extra")}
    assert {b for a, b in _edges(M, "contains") if a == "Demo stack"} == {"shop", "core", "extra"}   # (the code parser also uses `contains`)
    assert not any("demo.arch.yaml" in w for w in warnings)


def test_code_annotation_implements_a_component(tmp_path):
    _, M, _ = _build(tmp_path)
    assert any(d["relation"] == "implements" and M.nodes[v]["label"] == "core" for u, v, d in M.edges(data=True))


def test_gaps_name_the_component_with_no_code(tmp_path):
    ws, M, _ = _build(tmp_path)
    missing = {g["label"] for g in find_gaps(M, ws) if g["message"].startswith("component has no build artifact")}
    assert missing == {"shop", "extra"}          # `core` has `# implements: core` in its code
