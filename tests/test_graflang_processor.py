"""The `graflang` processor: GraphLang files become recipe/part/policy/procedure/error_code/bindings nodes with edges to what they name."""
import pytest

from workgraph.analyze import find_gaps
from workgraph.area import Workspace
from workgraph.pipeline import build_workspace

TOP = """version: "1.0-graph"
workflow:
  name: demo
  description: Does the demo.
  inputs: [{name: q, type: TEXT}]
  outputs: [{name: r, type: TEXT}]
resources:
  prompts: {ask: ./prompts/ask.md, spare: ./prompts/spare.md}
  policies: {safe: ./policies/safe.cedar}
  procedures: {long: ./procs/long.spl}
  parts: {check: ./check/check.graph.yaml, ghost: ./build/ghost.graph.yaml, named: "cookbook:thing"}
steps:
  - ask: {generate: prompts.ask, in: {q: $in.q}, out: a}
  - run: {node: SOLVE, backend: subprocess, command: ["python3", "-I", "tools/t.py"], out: o}
  - pick: {node: MUTATE, config: {catalogue: {other: ./other/other.graph.yaml}}}
"""
PART = """version: "1.0-graph"
workflow:
  name: check
  errors: [{name: bad, code: E_MINE}, {name: worse, code: E_NOWHERE}, {name: shipped, code: E_SHIPPED}]
resources: {}
steps: []
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    import workgraph.processors as P
    monkeypatch.setattr(P, "_shipped_error_codes", lambda: {"E_SHIPPED"})
    p = tmp_path / "proj"
    for d in ("prompts", "policies", "procs", "check", "tools", "other", "build", "tests"):
        (p / d).mkdir(parents=True)
    (p / "demo.graph.yaml").write_text(TOP)
    (p / "demo.bind.yaml").write_text("limits: {max_llm_calls: 5}\n")
    (p / "prompts" / "ask.md").write_text("Ask {{in_q}}\n")
    (p / "prompts" / "spare.md").write_text("never used\n")
    (p / "prompts" / "orphan.md").write_text("named by nobody\n")
    (p / "policies" / "safe.cedar").write_text("permit(principal, action, resource);\n")
    (p / "procs" / "long.spl").write_text("-- spl\n")
    (p / "tools" / "t.py").write_text("print(1)\n")
    (p / "check" / "check.graph.yaml").write_text(PART)
    (p / "other" / "other.graph.yaml").write_text(PART.replace("name: check", "name: other"))
    (p / "build" / "ghost.graph.yaml").write_text(PART.replace("name: check", "name: ghost"))      # `build/` is a noise folder the walk skips
    (p / "graflang.errors.yaml").write_text("errors:\n  - {code: E_MINE, description: mine}\n")
    (p / "tests" / "test_demo.py").write_text("def test_demo():\n    run('demo')\n")
    return p


def build(project, tmp_path, area="develop"):
    cfg = tmp_path / "workspace.yaml"
    cfg.write_text(f"area: {area}\nprojects:\n  - {{name: p, path: proj}}\n")
    ws = Workspace.load(cfg)
    M, _, warnings = build_workspace(ws)
    return ws, M, warnings


def edges(M, rel):
    return {(M.nodes[u].get("label"), M.nodes[v].get("label")) for u, v, d in M.edges(data=True) if d.get("relation") == rel}


def test_nodes_and_edges_of_a_small_project(project, tmp_path):
    ws, M, warnings = build(project, tmp_path)
    kinds = {M.nodes[n]["label"]: M.nodes[n]["kind"] for n in M if M.nodes[n].get("kind") in
             {"recipe", "part", "bindings", "error_code", "policy", "procedure"}}
    assert kinds == {"demo": "recipe", "check": "part", "other": "part", "demo (bindings)": "bindings", "E_MINE": "error_code",
                     "safe.cedar": "policy", "long.spl": "procedure"}
    assert edges(M, "uses") == {("demo", "check")}                        # `ghost` is in an ignored folder, `named` is GraphLang's to resolve
    assert edges(M, "may_add") == {("demo", "other")} and edges(M, "binds") == {("demo (bindings)", "demo")}
    assert edges(M, "governed_by") == {("demo", "safe.cedar")} and edges(M, "runs_procedure") == {("demo", "long.spl")}
    assert ("demo", "t.py") in edges(M, "runs")
    assert any(a == "demo" and b.startswith("ask") for a, b in edges(M, "reads_prompt"))          # to the prompt's own document node
    assert {("check", "E_MINE"), ("other", "E_MINE")} <= edges(M, "raises")
    assert ("test_demo.py", "demo") in edges(M, "verifies")
    verifies = [d for u, v, d in M.edges(data=True) if d.get("relation") == "verifies" and M.nodes[v].get("label") == "demo"]
    assert verifies and verifies[0]["confidence"] == "INFERRED"


def test_warnings_name_the_real_problems_only(project, tmp_path):
    _, _, warnings = build(project, tmp_path)
    text = "\n".join(warnings)
    assert "prompt `spare` is declared but no node uses it" in text
    assert "prompts/orphan.md: prompt file that no graph" in text
    assert "raises: E_NOWHERE" in text                                     # a code nobody defines
    assert "E_SHIPPED" not in text                                         # GraphLang's own catalogue defines it
    assert "ghost" not in text and "cookbook:thing" not in text            # ignored folder, named part: not the processor's business


def test_gap_rules_of_the_sdlc_pack(project, tmp_path):
    ws, M, _ = build(project, tmp_path)
    got = {(g["message"], g["label"]) for g in find_gaps(M, ws) if g["message"] in ("recipe has no test", "part is used by no recipe")}
    assert got == {("part is used by no recipe", "other")}                 # `demo` is named by a test; `check` is used; `other` is only in a catalogue
    (project / "tests" / "test_demo.py").write_text("def test_nothing():\n    pass\n")
    ws, M, _ = build(project, tmp_path)
    assert ("recipe has no test", "demo") in {(g["message"], g["label"]) for g in find_gaps(M, ws)}


def test_the_research_pack_lists_it_too_and_a_pack_without_it_gets_no_recipe_nodes(project, tmp_path):
    _, M, _ = build(project, tmp_path, area="research")
    assert any(d.get("kind") == "recipe" for _, d in M.nodes(data=True))
    _, M, _ = build(project, tmp_path, area="publish")                  # publish does not list the processor: opt-in
    assert not any(d.get("kind") in ("recipe", "part") for _, d in M.nodes(data=True))
