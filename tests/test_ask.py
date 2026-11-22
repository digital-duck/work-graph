"""`workgraph ask`: the recipe's four endings, with scripted model replies on the real graph of the examples."""
from pathlib import Path

import pytest

from workgraph import llm, paths, recipes
from workgraph.cli import main

EX = Path(__file__).parent.parent / "examples"
Q = "What design decision and test cover REQ-001?"
GOOD = "The design is [acme-shop:doc_adr_001] and the test is [acme-shop:tests_test_cart]."


@pytest.fixture
def graph(tmp_path):
    main(["build", "-c", str(EX / "workspace.yaml")])
    return str(paths.out_dir() / "graph.json")


def script(monkeypatch, *replies):
    seen = []

    def fake(prompt, **kw):
        seen.append(prompt)
        return replies[min(len(seen) - 1, len(replies) - 1)]

    monkeypatch.setattr(llm, "complete", fake)
    return seen


def ask(graph, q=Q, **kw):
    return recipes.Recipe("ask").run({"question": q, "graph": graph, "semantic": "no"}, backend="cc_cli", max_llm_calls=4, **kw)


def test_the_recipe_is_valid():
    r = recipes.Recipe("ask")                                          # loads and passes GraphLang's schema checks
    assert {i["name"] for i in r._graph["workflow"]["inputs"]} == {"question", "graph", "semantic"}


def test_a_cited_answer_is_grounded_and_the_model_saw_the_requirement_its_design_and_its_test(graph, monkeypatch):
    seen = script(monkeypatch, "REQ-001, design, test", GOOD)
    out = ask(graph)
    assert out["status"] == "grounded" and "Grounded in: acme-shop:doc_adr_001, acme-shop:tests_test_cart" in out["report"]
    facts = seen[1].split("Graph facts:")[1]
    assert "[acme-shop:doc_req_001]" in facts and "[acme-shop:tests_test_cart] --verifies--> [acme-shop:doc_req_001]" in facts
    assert len(seen) == 2                                              # search words, answer: no repair needed


def test_an_answer_that_cites_nothing_gets_one_second_try(graph, monkeypatch):
    seen = script(monkeypatch, "REQ-001", "ADR-001 and the cart test.", GOOD)
    out = ask(graph)
    assert out["status"] == "grounded" and len(seen) == 3
    assert "cites no node id" in seen[2]                               # the repair prompt says what was wrong


def test_an_invented_id_is_never_passed_off_as_grounded(graph, monkeypatch):
    seen = script(monkeypatch, "REQ-001", "See [acme-shop:made_up].", "Still [acme-shop:also_made_up].")
    out = ask(graph)
    assert out["status"] == "ungrounded" and len(seen) == 3
    assert out["report"].startswith("UNGROUNDED") and "also_made_up" in out["report"] and "Do not rely on it" in out["report"]


def test_no_match_means_no_model_answer(graph, monkeypatch):
    seen = script(monkeypatch, "zzzzqq")
    out = ask(graph, q="zzzzqq xxyyzz")
    assert out["status"] == "empty" and "nothing that matches" in out["report"]
    assert len(seen) == 1                                              # only the search words: nothing to answer from


def test_the_call_cap_holds(graph, monkeypatch):
    script(monkeypatch, "REQ-001", "none", "none")
    with pytest.raises(RuntimeError, match="max_llm_calls"):
        recipes.Recipe("ask").run({"question": Q, "graph": graph, "semantic": "no"}, backend="cc_cli", max_llm_calls=2)


def test_the_command_prints_the_report_and_exits_nonzero_unless_grounded(graph, monkeypatch, capsys):
    script(monkeypatch, "REQ-001", GOOD)
    main(["ask", Q])
    out = capsys.readouterr().out
    assert "Grounded in:" in out and "[grounded]" in out
    script(monkeypatch, "REQ-001", "no cites", "still none")
    with pytest.raises(SystemExit) as e:
        main(["ask", Q])
    assert e.value.code == 1 and "[ungrounded]" in capsys.readouterr().out


def test_a_missing_graph_says_to_build_first(monkeypatch):
    with pytest.raises(SystemExit, match="workgraph build"):
        main(["ask", Q])
