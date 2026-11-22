from pathlib import Path

import pytest

from workgraph.area import Area, available_areas


def test_all_packs_load_and_are_consistent():
    assert {"sdlc", "research", "publishing"} <= set(available_areas())
    for name in available_areas():
        d = Area.load(name)
        assert d.stages and d.flow_relations and d.processors


def test_classify_multi_tag_and_default():
    d = Area.load("sdlc")
    assert d.classify("tests/test_x.py") == ["test"]
    assert d.classify("src/app.py") == ["build"]
    assert d.classify("docs/design/specs/api.md") == ["requirement", "design"]
    assert Area.load("research").classify("scripts/run.py") == ["experiment"]  # code is an experiment there


def test_stage_tags_are_constrained():
    d = Area.load("sdlc")
    assert d.validate_stages(["build", "test", "build"]) == ["build", "test"]
    with pytest.raises(ValueError, match="unknown stage"):
        d.validate_stages(["hypothesis"])  # a research stage is not an sdlc stage


def test_classify_real_world_conventions():
    d = Area.load("sdlc")
    assert d.classify("docs/DEV/readme-roadmap.md") == ["requirement", "design"]   # multi-tag
    assert d.classify("DESIGN.md") == ["design"]
    assert d.classify("CLAUDE.md") == ["design"]
    assert d.classify("docs/GUIDE/Tutorial.md") == ["release"]
    assert d.classify("src/App.js") == ["build"]
    assert d.classify("scripts/test_gen.sh") == ["test"]


def test_validate_pack_accepts_every_shipped_pack():
    from workgraph.area import validate_pack
    for name in available_areas():
        assert validate_pack(name) == [], name


def test_validate_pack_reports_every_problem(tmp_path):
    from workgraph.area import validate_pack
    bad = tmp_path / "bad.yaml"
    bad.write_text("""
area: demo
stages:
  - {id: a, next: [b, zzz]}
  - {id: b}
  - {id: b}
flow_relations:
  - {from: a, to: nope, relation: feeds}
expectations:
  - {stage: a, needs: missing, message: m}
classifiers:
  - {stage: a}
  - {stage: q, default: true}
processors:
  - {name: x, use: telepathy}
""", encoding="utf-8")
    errs = "\n".join(validate_pack(bad))
    for needle in ("unknown stage 'zzz'", "duplicate stage id 'b'", "unknown stage 'nope'",
                   "`needs` 'missing'", "non-empty `globs`", "unknown stage 'q'", "unknown `use` 'telepathy'"):
        assert needle in errs, needle
    assert validate_pack(tmp_path / "absent.yaml")[0].startswith("pack not found")
    broken = tmp_path / "broken.yaml"
    broken.write_text("area: [", encoding="utf-8")
    assert validate_pack(broken)[0].startswith("invalid YAML")


def test_validate_pack_cli_exit_code(tmp_path, capsys):
    from workgraph import cli
    ok = ["sdlc"]
    bad = tmp_path / "p.yaml"
    bad.write_text("stages: []\n", encoding="utf-8")
    cli.cmd_validate_pack(type("A", (), {"pack": ok})())
    assert "[ok] sdlc" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.cmd_validate_pack(type("A", (), {"pack": [str(bad)]})())
    assert "[!!]" in capsys.readouterr().out


# ---- the 0.3.0 rename: `domain` (a pack) became `area` -----------------------------------------------------------------------------------------------------

def test_a_workspace_file_with_the_old_domain_key_still_loads_and_warns_once(tmp_path, capsys):
    from workgraph import area
    area._WARNED.clear()
    ws = tmp_path / "workspace.yaml"
    (tmp_path / "p").mkdir()
    ws.write_text("domain: sdlc\nprojects:\n  - {name: p, path: p, domain: research}\n", encoding="utf-8")
    loaded = area.Workspace.load(ws)
    assert loaded.projects[0].area.name == "research"
    err = capsys.readouterr().err
    assert "`domain:` is now `area:`" in err and "workgraph utils migrate" in err
    area.Workspace.load(ws)
    assert capsys.readouterr().err == ""                      # said once, not on every load


def test_a_custom_pack_with_the_old_key_loads_and_validate_pack_says_to_migrate(tmp_path):
    from workgraph import area
    pack = tmp_path / "old.yaml"
    pack.write_text((Path(area.AREAS_DIR) / "sdlc.yaml").read_text(encoding="utf-8").replace("area: sdlc", "domain: old", 1), encoding="utf-8")
    assert area.Area.load(pack).name == "old"
    assert any("`domain:` is now `area:`" in e for e in area.validate_pack(pack))


def test_migrate_moves_the_custom_packs_and_rewrites_the_old_key_and_is_safe_twice(tmp_path):
    from workgraph import migrate, paths
    (paths.custom_dir() / "domains").mkdir(parents=True)
    (paths.custom_dir() / "domains" / "mine.yaml").write_text("domain: mine\nstages: []\n", encoding="utf-8")
    ws = tmp_path / "workspace.yaml"
    ws.write_text("# my projects\ndomain: sdlc   # default\nprojects:\n  - {name: a, path: a, domain: research}\n", encoding="utf-8")
    dry = migrate.migrate([ws], dry=True)
    assert dry and "domain: mine" in (paths.custom_dir() / "domains" / "mine.yaml").read_text(encoding="utf-8")       # nothing written
    done = migrate.migrate([ws])
    assert (paths.custom_areas_dir() / "mine.yaml").read_text(encoding="utf-8").startswith("area: mine")
    assert not (paths.custom_dir() / "domains").exists()
    text = ws.read_text(encoding="utf-8")
    assert "# my projects" in text and "area: sdlc   # default" in text and "{name: a, path: a, area: research}" in text and "domain" not in text
    assert done and migrate.migrate([ws]) == []                                                                          # the second run finds nothing


def test_init_home_moves_an_old_custom_domains_folder_to_areas():
    from workgraph import paths, tracking
    (paths.custom_dir() / "domains").mkdir(parents=True)
    (paths.custom_dir() / "domains" / "x.yaml").write_text("domain: x\n", encoding="utf-8")
    tracking.init_home()
    assert (paths.custom_areas_dir() / "x.yaml").exists() and not (paths.custom_dir() / "domains").exists()


def test_a_graph_built_before_the_rename_is_refused_with_a_rebuild_message():
    import networkx as nx
    from workgraph import query
    old = nx.MultiDiGraph()
    old.add_node("a", domain="sdlc", layer="process")
    try:
        query.check_format(old, "graph.json")
    except ValueError as e:
        assert "run `workgraph build` again" in str(e)
    else:
        raise AssertionError("an unmarked graph with the old keys must be refused")
    old.graph["workgraph_format"] = 2
    assert query.check_format(old) is old
    new = nx.MultiDiGraph()
    new.add_node("a", area="sdlc", domain="process")           # new words, hand-built, no mark: fine
    assert query.check_format(new) is new
