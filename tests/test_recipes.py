"""The `extract_items` recipe (GraphLang) and the `llm_items` processor that runs it, against the old Python path and with scripted model replies."""
import json

import pytest

from workgraph import llm, paths, recipes
from workgraph.area import Workspace
from workgraph.pipeline import build_workspace

REPLY = "Sure!\n```json\n" + json.dumps({"items": [
    {"title": "Support SSO", "kind": "requirement", "stages": ["requirement", "bogus"], "status": "open", "summary": "s"},
    {"title": "Ignore me", "kind": "nonsense", "stages": ["build"]},
    "not a mapping", {"kind": "task"}]}) + "\n```"
INPUTS = dict(area="develop", kinds="requirement, task", stages="requirement, design", flow="requirement->design", max_items="40",
              path="docs/ROADMAP.md", text="# Roadmap\n- [ ] Support SSO")


@pytest.fixture
def prompts_seen(monkeypatch):
    seen = []

    def fake(prompt, *, backend, max_tokens=4096, allowed_tools=None):
        seen.append(prompt)
        return REPLY

    monkeypatch.setattr(llm, "complete", fake)
    return seen


def test_the_recipe_is_valid_and_has_the_interface():
    assert recipes.check_recipe("extract_items") is None
    assert recipes.check_recipe("nope") and "no recipe named" in recipes.check_recipe("nope")


def test_the_recipe_builds_the_same_prompt_as_the_python_path_and_keeps_only_allowed_items(prompts_seen):
    from workgraph.processors import _ITEMS_PROMPT
    out = recipes.Recipe("extract_items").run(INPUTS, backend="cc_cli")
    old = _ITEMS_PROMPT.format(area="develop", kinds="requirement, task", stages="requirement, design", flow="requirement->design", max_items=40,
                               path="docs/ROADMAP.md", text=INPUTS["text"])
    assert prompts_seen == [old]                                         # byte for byte
    items = json.loads(out["items"])["items"]
    assert [(i["title"], i["kind"], i["stages"]) for i in items] == [("Support SSO", "requirement", ["requirement"])]


def test_a_reply_without_json_gives_no_items(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda p, **k: "I cannot do that.")
    assert json.loads(recipes.Recipe("extract_items").run(INPUTS, backend="cc_cli")["items"]) == {"items": []}


def test_a_document_that_mentions_a_placeholder_is_not_expanded(prompts_seen):
    recipes.Recipe("extract_items").run({**INPUTS, "text": "see {{in_path}} and {{kinds}}"}, backend="cc_cli")
    assert "see {{in_path}} and {{kinds}}" in prompts_seen[0]


def test_a_backend_limit_passes_through_the_recipe(monkeypatch):
    def limit(prompt, **k):
        raise llm.BackendLimitError("session limit")
    monkeypatch.setattr(llm, "complete", limit)
    with pytest.raises(llm.BackendLimitError):
        recipes.Recipe("extract_items").run(INPUTS, backend="cc_cli")


def _ws(tmp_path, pack_extra=""):
    (tmp_path / "p" / "docs").mkdir(parents=True)
    (tmp_path / "p" / "docs" / "ROADMAP.md").write_text("# Roadmap\n- [ ] Support SSO\n")
    cfg = tmp_path / "workspace.yaml"
    cfg.write_text("area: develop\nprojects:\n  - {name: p, path: p}\n")
    return Workspace.load(cfg)


def _items(M):
    return sorted((d["label"], d["kind"], tuple(d["stages"]), d["status"]) for _, d in M.nodes(data=True) if d.get("origin") == "llm")


def test_recipe_path_and_python_path_give_the_same_nodes(tmp_path, monkeypatch, prompts_seen):
    monkeypatch.setenv("WORKGRAPH_CACHE", str(tmp_path / "cache"))
    ws = _ws(tmp_path)
    new, _, _ = build_workspace(ws, semantic=True)
    monkeypatch.setenv("WORKGRAPH_LLM_ITEMS", "python")
    monkeypatch.setenv("WORKGRAPH_CACHE", str(tmp_path / "cache2"))
    old, _, _ = build_workspace(ws, semantic=True)
    assert _items(new) and _items(new) == _items(old)
    assert sorted(new.nodes) == sorted(old.nodes) and new.number_of_edges() == old.number_of_edges()


def test_the_cache_still_serves_a_rerun(tmp_path, monkeypatch, prompts_seen):
    monkeypatch.setenv("WORKGRAPH_CACHE", str(tmp_path / "cache"))
    ws = _ws(tmp_path)
    build_workspace(ws, semantic=True)
    build_workspace(ws, semantic=True)
    assert len(prompts_seen) == 1


def test_a_custom_recipe_in_home_wins_and_a_custom_prompt_replaces_the_prompt(tmp_path, monkeypatch, prompts_seen):
    import shutil
    home_recipes = paths.custom_dir() / "recipes"
    shutil.copytree(recipes.SHIPPED / "extract_items", home_recipes / "extract_items")
    (home_recipes / "extract_items" / "prompts" / "extract.md").write_text("MINE {{in_path}} {{in_text}}\n")
    assert recipes.recipe_path("extract_items").parent == home_recipes / "extract_items"
    recipes.Recipe("extract_items").run(INPUTS, backend="cc_cli")
    assert prompts_seen[-1].startswith("MINE docs/ROADMAP.md")
    shutil.rmtree(home_recipes / "extract_items")
    custom = paths.custom_dir() / "prompts"
    custom.mkdir(parents=True, exist_ok=True)
    (custom / "items.md").write_text("PACK {{in_area}} {{in_path}}\n")
    recipes.Recipe("extract_items", prompt="items.md").run(INPUTS, backend="cc_cli")
    assert prompts_seen[-1].startswith("PACK develop docs/ROADMAP.md")
    assert recipes.check_prompt("items.md") is None and "not found" in recipes.check_prompt("zzz.md")


def test_validate_pack_checks_recipe_and_prompt_names(tmp_path):
    from workgraph.area import validate_pack
    base = ("area: x\nstages:\n  - {id: a, label: A}\nflow_relations: []\nexpectations: []\nclassifiers: [{stage: a, default: true}]\n"
            "processors:\n  - {name: items, use: llm_items, %s}\n")
    bad = tmp_path / "bad.yaml"
    bad.write_text(base % "recipe: nope, prompt: nope.md")
    errs = "\n".join(validate_pack(bad))
    assert "no recipe named" in errs and "prompt file 'nope.md' not found" in errs
    ok = tmp_path / "ok.yaml"
    ok.write_text(base % "recipe: extract_items")
    assert not [e for e in validate_pack(ok) if "recipe" in e]
