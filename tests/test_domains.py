import json
import shutil
from pathlib import Path

import pytest

from workgraph import paths
from workgraph.convert import json_to_yaml, yaml_to_json
from workgraph.area import Workspace
from workgraph.pipeline import build_workspace
from workgraph.schema import validate_domain
from workgraph.store import Store

EX = Path(__file__).parent.parent / "examples"


def _doc(domain="org", nodes=None, edges=None):
    return {"schema": "workgraph/2", "domain": domain, "nodes": nodes or [], "edges": edges or []}


def test_schema_accepts_valid_and_rejects_each_rule():
    ok = _doc(nodes=[{"id": "org:a", "kind": "company"}, {"id": "org:a/b", "kind": "team"}],
              edges=[{"source": "org:a/b", "target": "org:a", "relation": "part_of"}])
    assert validate_domain(ok) == []
    bad = {
        "wrong prefix": _doc(nodes=[{"id": "product:a", "kind": "company"}]),
        "bad kind": _doc(nodes=[{"id": "org:a", "kind": "planet"}]),
        "duplicate": _doc(nodes=[{"id": "org:a", "kind": "team"}, {"id": "org:a", "kind": "team"}]),
        "bad uid": _doc(nodes=[{"id": "org:a", "kind": "team", "uid": "xyz"}]),
        "unknown relation": _doc(edges=[{"source": "org:a", "target": "org:b", "relation": "likes"}]),
        "wrong domains": _doc(edges=[{"source": "org:a", "target": "org:b", "relation": "owned_by"}]),
        "cycle": _doc(edges=[{"source": "org:a", "target": "org:b", "relation": "part_of"},
                             {"source": "org:b", "target": "org:a", "relation": "part_of"}]),
        "bad domain": {**_doc(), "domain": "galaxy"},
    }
    for name, doc in bad.items():
        assert validate_domain(doc), name


def test_example_domains_merge_into_one_graph():
    M, _, warnings = build_workspace(Workspace.load(EX / "workspace.yaml"))
    assert {d["domain"] for _, d in M.nodes(data=True)} == {"repo", "process", "product", "org"}
    rels = {(u, d["relation"], v) for u, v, d in M.edges(data=True)}
    assert ("project:acme-shop", "belongs_to", "product:acme/retail/shop/checkout") in rels
    assert ("product:acme/retail/shop", "follows", "process:develop") in rels   # pack-derived process node
    assert ("stage:develop:design", "part_of", "process:develop") in rels
    assert not [w for w in warnings if ".json" in w or ".yaml" in w]


def _copy_graphs(tmp_path):
    ws = tmp_path / "ws"
    shutil.copytree(EX, ws, ignore=shutil.ignore_patterns("store.sqlite", "*.yaml", "graphs"))
    shutil.copytree(EX / "graphs", ws / "graphs", ignore=shutil.ignore_patterns("store.sqlite", "*.yaml"))
    (ws / "workspace.yaml").write_text((EX / "workspace.yaml").read_text())
    return ws


def test_broken_reference_and_rename_hint(tmp_path):
    ws = _copy_graphs(tmp_path)
    org = ws / "graphs" / "org.json"
    doc = json.loads(org.read_text())
    with Store(paths.store_path()) as store:
        store.remember_ids("org", doc["nodes"])               # history before the rename
    old = "org:acme/engineering/commerce/payments"
    for n in doc["nodes"]:
        n["id"] = n["id"].replace(old, "org:acme/engineering/commerce/billing") if n["id"].startswith(old) else n["id"]
    for e in doc["edges"]:
        for k in ("source", "target"):
            e[k] = e[k].replace(old, "org:acme/engineering/commerce/billing")
    org.write_text(json.dumps(doc))
    _, _, warnings = build_workspace(Workspace.load(ws / "workspace.yaml"))
    hit = [w for w in warnings if old in w]
    assert hit and "renamed to org:acme/engineering/commerce/billing" in hit[0]


def test_subgraph_reference_expands_to_descendants(tmp_path):
    ws = _copy_graphs(tmp_path)
    prod = ws / "graphs" / "product.json"
    doc = json.loads(prod.read_text())
    doc["edges"].append({"source": "product:acme/retail/**", "target": "process:develop", "relation": "follows"})
    prod.write_text(json.dumps(doc))
    M, _, _ = build_workspace(Workspace.load(ws / "workspace.yaml"))
    followers = {u for u, v, d in M.edges(data=True) if v == "process:develop" and d["relation"] == "follows"}
    assert {"product:acme/retail", "product:acme/retail/shop", "product:acme/retail/shop/checkout"} <= followers


def test_json_yaml_round_trip_keeps_content_and_comments(tmp_path):
    src = tmp_path / "product.json"
    src.write_text((EX / "graphs" / "product.json").read_text())
    original = json.loads(src.read_text())
    y = tmp_path / "product.yaml"
    with Store(tmp_path / "store.sqlite") as store:
        json_to_yaml(src, y, store)
        text = y.read_text()
        text = text.replace("  - id: product:acme/retail/shop\n", "  # the flagship product\n  - id: product:acme/retail/shop\n")
        text = text.replace("    kind: application\n", "    kind: application  # deployable\n")
        y.write_text("# hand-written header\n" + text)
        yaml_to_json(y, src, store)
        assert json.loads(src.read_text()) == original          # comments never reach the JSON
        y.unlink()
        info = json_to_yaml(src, y, store)                      # regenerate YAML from JSON alone
        assert info["orphans"] == 0
    out = y.read_text()
    assert "# hand-written header" in out
    assert "# the flagship product\n  - id: product:acme/retail/shop\n" in out
    assert "kind: application  # deployable" in out


def test_comment_added_in_yaml_survives_next_convert_and_orphan_is_kept(tmp_path):
    src, y = tmp_path / "org.json", tmp_path / "org.yaml"
    src.write_text((EX / "graphs" / "org.json").read_text())
    with Store(tmp_path / "store.sqlite") as store:
        json_to_yaml(src, y, store)
        y.write_text(y.read_text().replace("    label: Research\n", "    label: Research  # to be renamed\n"))
        # regenerate without running yaml_to_json first: the edit must be harvested, not overwritten
        json_to_yaml(src, y, store)
        assert "label: Research  # to be renamed" in y.read_text()
        doc = json.loads(src.read_text())
        doc["nodes"] = [n for n in doc["nodes"] if n["id"] != "org:acme/engineering/research"]
        doc["edges"] = [e for e in doc["edges"] if "research" not in e["source"]]
        src.write_text(json.dumps(doc))
        info = json_to_yaml(src, y, store)
    assert info["orphans"] == 1
    assert "# [orphaned from org:acme/engineering/research] to be renamed" in y.read_text()
    with Store(tmp_path / "store.sqlite") as store:               # the orphan is itself preserved on the next pass
        json_to_yaml(src, y, store)
    assert "[orphaned from org:acme/engineering/research] to be renamed" in y.read_text()


def test_invalid_domain_file_is_reported_not_loaded(tmp_path):
    ws = _copy_graphs(tmp_path)
    (ws / "graphs" / "org.json").write_text(json.dumps(_doc(nodes=[{"id": "org:a", "kind": "planet"}])))
    _, _, warnings = build_workspace(Workspace.load(ws / "workspace.yaml"))
    assert any("planet" in w for w in warnings)
    assert any("broken reference org:acme" in w for w in warnings)   # product.json now points at missing org nodes


def test_custom_process_domain_file_merges_with_ordered_steps():
    M, _, _ = build_workspace(Workspace.load(EX / "workspace.yaml"))
    rels = {(u, d["relation"], v) for u, v, d in M.edges(data=True)}
    steps = ["interview", "requirements", "design", "prototype", "build", "test", "release", "feedback"]
    for a, b in zip(steps, steps[1:]):
        assert (f"process:delivery/{a}", "precedes", f"process:delivery/{b}") in rels
    assert all((f"process:delivery/{s}", "part_of", "process:delivery") in rels for s in steps)
    assert ("product:acme/retail/shop", "follows", "process:delivery") in rels
    assert ("product:acme/retail/shop", "follows", "process:develop") in rels


# ---- the 0.3.0 rename: `layer` (org, product, process, repo) became `domain` -----------------------------------------------------------------------------------

def test_a_domain_file_written_by_0_2_reads_as_the_new_form_with_a_note():
    from workgraph.schema import normalize_legacy, validate_domain
    doc = {"schema": "workgraph/1", "layer": "org", "nodes": [{"id": "org:a", "kind": "company", "label": "A"}], "edges": []}
    assert "migrate" in normalize_legacy(doc)[0]
    assert doc["domain"] == "org" and "layer" not in doc and doc["schema"] == "workgraph/2" and validate_domain(doc) == []
    assert normalize_legacy(doc) == []                                    # a new file has nothing to say


def test_the_loader_accepts_an_old_file_and_warns(tmp_path):
    import json
    from workgraph.refs import load_domains
    (tmp_path / "org.json").write_text(json.dumps({"schema": "workgraph/1", "layer": "org", "nodes": [{"id": "org:a", "kind": "company", "label": "A"}], "edges": []}), encoding="utf-8")
    docs, notes = load_domains(tmp_path)
    assert list(docs) == ["org.json"] and docs["org.json"]["domain"] == "org" and any("0.2.x" in n for n in notes)


def test_migrate_rewrites_a_domain_file_and_its_yaml_twin_and_drops_the_old_output(tmp_path):
    import json
    from workgraph import migrate, paths
    g = tmp_path / "graphs"
    g.mkdir()
    (g / "org.json").write_text(json.dumps({"schema": "workgraph/1", "layer": "org", "nodes": [], "edges": []}, indent=2) + "\n", encoding="utf-8")
    (g / "org.yaml").write_text("schema: workgraph/1\nlayer: org   # the company\nnodes: []\nedges: []\n", encoding="utf-8")
    ws = tmp_path / "workspace.yaml"
    ws.write_text("projects: []\n", encoding="utf-8")
    (paths.out_dir() / "layers").mkdir(parents=True)
    assert migrate.migrate([ws], dry=True) and (paths.out_dir() / "layers").exists()            # a dry run writes nothing
    migrate.migrate([ws])
    new = json.loads((g / "org.json").read_text(encoding="utf-8"))
    assert new == {"schema": "workgraph/2", "domain": "org", "nodes": [], "edges": []} and list(new)[:2] == ["schema", "domain"]
    assert (g / "org.yaml").read_text(encoding="utf-8").startswith("schema: workgraph/2\ndomain: org   # the company")
    assert not (paths.out_dir() / "layers").exists() and migrate.migrate([ws]) == []


def test_a_database_of_0_2_gets_its_layer_columns_renamed(tmp_path):
    import sqlite3
    from workgraph.store import Store
    db = tmp_path / "old.sqlite3"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE files (path TEXT PRIMARY KEY, layer TEXT, json_sha256 TEXT, yaml_sha256 TEXT, updated_at REAL);"
                      "CREATE TABLE node_ids (uid TEXT, id TEXT, layer TEXT, last_seen REAL, PRIMARY KEY (uid, id));"
                      "INSERT INTO node_ids VALUES ('u1', 'org:a', 'org', 1.0);")
    con.commit()
    con.close()
    with Store(db) as s:
        assert s.dump_node_ids(set()) == [{"uid": "u1", "id": "org:a", "domain": "org"}]
        assert s.merge_node_ids([{"uid": "u2", "id": "org:b", "domain": "org"}]) == 1
