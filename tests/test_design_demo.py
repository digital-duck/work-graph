"""examples/graphware-demo: the design area on a small hardware-and-software product, with deliberate gaps the demo's README lists."""
from pathlib import Path

from workgraph.analyze import find_gaps
from workgraph.area import Workspace
from workgraph.pipeline import build_workspace

DEMO = Path(__file__).parent.parent / "examples" / "graphware-demo"


def _gaps():
    ws = Workspace.load(DEMO / "workspace.yaml")
    M, _, warnings = build_workspace(ws)
    return M, warnings, {(g["message"].split(" (")[0], g["label"].split(":")[0]) for g in find_gaps(M, ws)}


def test_the_demo_has_exactly_the_gaps_its_readme_lists():
    _, warnings, got = _gaps()
    assert got == {
        ("idea has no spec", "IDEA-002"),
        ("spec has no design", "SPEC-002"),
        ("spec has no test", "SPEC-002"),
        ("component has no build artifact", "app"),
        ("component has no test", "app"), ("component has no test", "api"),
        ("component has no test", "moisture sensor"), ("component has no test", "pump"),
    }
    assert warnings == []


def test_the_whole_chain_is_linked_idea_to_spec_to_design_to_build_to_test():
    M, _, _ = _gaps()
    rel = {(M.nodes[u].get("label", "").split(":")[0], d["relation"], M.nodes[v].get("label", "").split(":")[0]) for u, v, d in M.edges(data=True)}
    assert ("SPEC-001", "refines", "IDEA-001") in rel                        # spec -> idea
    assert ("firmware", "satisfies", "SPEC-001") in rel                      # design -> spec
    assert any(a == "firmware.py" and r == "implements" and b == "firmware" for a, r, b in rel)     # build -> design (code)
    assert any(r == "implements" and b == "pump" for a, r, b in rel) and any(r == "implements" and b == "moisture sensor" for a, r, b in rel)   # build -> design (the BOM)
    assert any(a == "test_firmware.py" and r == "verifies" and b == "SPEC-001" for a, r, b in rel)   # test -> spec
    assert any(a == "test_firmware.py" and r == "verifies" and b == "firmware" for a, r, b in rel)   # test -> design


def test_the_architecture_file_is_valid_for_graflangs_tools():
    import pytest
    arch2mmd = pytest.importorskip("graphlang.grafu.arch2mmd", reason="needs graflang")
    mmd2arch = pytest.importorskip("graphlang.grafu.mmd2arch")
    arch = arch2mmd.load(DEMO / "design" / "plant-waterer.arch.yaml")
    assert arch2mmd.validate(arch)[0] == [] and mmd2arch.roundtrip_arch(arch) == []
