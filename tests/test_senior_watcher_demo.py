"""examples/senior-watcher: the design area on a home-care product made of reused phones, with deliberate gaps the demo's README lists."""
from pathlib import Path

from workgraph.analyze import find_gaps
from workgraph.area import Workspace
from workgraph.pipeline import build_workspace

DEMO = Path(__file__).parent.parent / "examples" / "senior-watcher"


def _build():
    ws = Workspace.load(DEMO / "workspace.yaml")
    M, _, warnings = build_workspace(ws)
    return M, warnings, {(g["message"].split(" (")[0], g["label"].split(":")[0]) for g in find_gaps(M, ws)}


def _relations(M):
    return {(M.nodes[u].get("label", "").split(":")[0], d["relation"], M.nodes[v].get("label", "").split(":")[0]) for u, v, d in M.edges(data=True)}


def test_the_demo_has_exactly_the_gaps_its_readme_lists():
    _, warnings, got = _build()
    assert got == {
        ("idea has no spec", "IDEA-003"),
        ("spec has no design", "SPEC-005"),
        ("spec has no test", "SPEC-003"), ("spec has no test", "SPEC-004"), ("spec has no test", "SPEC-005"),
        ("component has no build artifact", "caregiver view"),
        ("component has no test", "caregiver view"), ("component has no test", "room monitor"), ("component has no test", "room phone"),
    }
    assert warnings == []


def test_the_fall_chain_is_linked_idea_to_spec_to_design_to_build_to_test():
    rel = _relations(_build()[0])
    assert ("SPEC-001", "refines", "IDEA-001") in rel
    assert ("alert engine", "satisfies", "SPEC-001") in rel and ("wearable app", "satisfies", "SPEC-001") in rel
    assert any(a == "alert_engine.py" and r == "implements" and b == "alert engine" for a, r, b in rel)
    assert any(a == "test_fall.py" and r == "verifies" and b == "SPEC-001" for a, r, b in rel)
    assert any(a == "test_alert_engine.py" and r == "verifies" and b == "SPEC-002" for a, r, b in rel)


def test_hardware_is_built_by_the_bom_and_tested_by_a_manual_checklist():
    rel = _relations(_build()[0])
    for phone in ("hub phone", "worn phone", "room phone"):
        assert any(r == "implements" and b == phone for a, r, b in rel), phone
    assert any(r == "verifies" and b == "hub phone" for a, r, b in rel)
    assert any(r == "verifies" and b == "worn phone" for a, r, b in rel)
    assert not any(r == "verifies" and b == "room phone" for a, r, b in rel)     # the deliberate hardware gap


def test_the_architecture_file_is_valid_for_graflangs_tools():
    import pytest
    arch2mmd = pytest.importorskip("graphlang.grafu.arch2mmd", reason="needs graflang")
    mmd2arch = pytest.importorskip("graphlang.grafu.mmd2arch")
    arch = arch2mmd.load(DEMO / "design" / "senior-watcher.arch.yaml")
    assert arch2mmd.validate(arch) == ([], []) and mmd2arch.roundtrip_arch(arch) == []
