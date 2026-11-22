import json
from pathlib import Path

import networkx as nx
import pytest

from workgraph import domains
from workgraph.cli import main
from workgraph.query import load_graph

EX = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def built(tmp_path):
    out = tmp_path / "out"
    main(["build", "-c", str(EX / "workspace.yaml"), "--out", str(out), "--quiet"])
    return out


def test_domain_map_is_derived_from_the_vocabulary():
    G = domains.domain_map()
    assert set(G) == {"repo", "product", "org", "process"}
    assert {(u, v, r) for u, v, d in G.edges(data=True) for r in d["relations"]} == {
        ("repo", "product", "belongs_to"), ("product", "org", "owned_by"), ("product", "process", "follows"),
        ("repo", "process", "in_stage"), ("repo", "process", "participates_in")}
    rank = {n: d["rank"] for n, d in G.nodes(data=True)}
    assert rank == {"repo": 0, "product": 1, "org": 2, "process": 2}   # relative: org and process are siblings
    assert domains.coarser(G, "repo") == ["product", "process"] and domains.finer(G, "product") == ["repo"]
    assert domains.by_coarseness(G)[-1] == "repo"
    assert G.nodes["repo"]["hierarchical"] is False and G.nodes["org"]["hierarchical"] is True


def test_a_new_domain_shifts_the_ranks(monkeypatch):
    from workgraph import schema
    monkeypatch.setitem(schema.DOMAIN_KINDS, "market", {"segment"})
    rules = {**schema.RELATION_RULES, "targets": ({"org"}, {"market"})}
    monkeypatch.setattr(domains, "RELATION_RULES", rules)
    G = domains.domain_map()
    assert G.nodes["market"]["rank"] == 3 and G.nodes["org"]["rank"] == 2


def test_a_dependency_cycle_is_rejected(monkeypatch):
    rules = {**domains.RELATION_RULES, "back": ({"org"}, {"repo"})}
    monkeypatch.setattr(domains, "RELATION_RULES", rules)
    with pytest.raises(ValueError, match="cycle"):
        domains.domain_map()


def test_build_writes_partitions_that_add_up_to_graph_json(built):
    M = load_graph(built / "graph.json")
    d = built / "domains"
    meta = domains.load_meta(d)
    assert meta["format"] == domains.FORMAT
    assert sum(x["nodes"] for x in meta["domains"]) == M.number_of_nodes()
    seen: dict[str, str] = {}
    for x in meta["domains"]:
        for n in domains.load_domain(x["id"], d).nodes:
            assert n not in seen, f"{n} in {seen[n]} and {x['id']}"       # each node in exactly one partition
            seen[n] = x["id"]
    assert set(seen) == set(M.nodes)
    cross = domains.load_cross(d)
    inner = sum(x["edges"] for x in meta["domains"])
    assert inner + len(cross) == M.number_of_edges()
    assert all(domains.node_domain(M, e["source"]) != domains.node_domain(M, e["target"]) for e in cross)


def test_load_scope_is_the_induced_subgraph(built):
    M = load_graph(built / "graph.json")
    d = built / "domains"
    S = domains.load_scope(["repo", "product"], d)
    keep = [n for n in M if domains.node_domain(M, n) in ("repo", "product")]
    want = M.subgraph(keep)
    assert set(S.nodes) == set(want.nodes)
    assert S.number_of_edges() == want.number_of_edges()
    assert nx.is_isomorphic(nx.DiGraph(S), nx.DiGraph(want))


def test_rebuild_replaces_stale_partitions(built):
    d = built / "domains"
    (d / "ghost.json").write_text("{}", encoding="utf-8")
    domains.write_partitions(load_graph(built / "graph.json"), d)
    assert not (d / "ghost.json").exists()


def test_context_loads_only_the_domains_it_needs(built, monkeypatch):
    d = built / "domains"
    loaded: list[str] = []
    real = domains.load_domain
    monkeypatch.setattr(domains, "load_domain", lambda name, out=None: (loaded.append(name), real(name, out))[1])
    linked = {e["target"] for e in domains.load_cross(d) if e["relation"] == "belongs_to"}
    prod = next(iter(linked))
    loaded.clear()
    ctx = domains.context(prod, d)
    assert ctx["domain"] == "product" and ctx["finer"]
    assert set(loaded) == set(ctx["loaded"]) == {"product", "repo"}      # repo only because a project points here
    # a node with no cross-domain neighbours in repo must not pull the repo partition in
    org = next(n for n in domains.load_domain("org", d).nodes if not any(
        domains.domain_of(e["source"]) == "repo" or domains.domain_of(e["target"]) == "repo"
        for e in domains.load_cross(d) if n in (e["source"], e["target"])))
    loaded.clear()
    domains.context(org, d)
    assert "repo" not in loaded
    with pytest.raises(KeyError):
        domains.context("org:nope", d)


def test_context_groups_neighbours_by_relative_coarseness(built):
    d = built / "domains"
    M = load_graph(built / "graph.json")
    proj = next(n for n, a in M.nodes(data=True) if a.get("kind") == "project"
                and any(e["relation"] == "belongs_to" and e["source"] == n for e in domains.load_cross(d)))
    ctx = domains.context(proj, d)
    assert any(x["domain"] == "product" and x["relation"] == "belongs_to" for x in ctx["coarser"])
    prod = next(x["id"] for x in ctx["coarser"])
    assert any(x["id"] == proj for x in domains.context(prod, d)["finer"])      # the same link seen from above


def test_dot_shows_counts_and_ranks(built):
    G = domains.domain_map()
    dot = domains.to_dot(G, domains.load_meta(built / "domains"))
    assert "rankdir=BT" in dot and "belongs_to" in dot and "nodes," in dot
    assert 'label="in_stage (' in dot and "\\nparticipates_in (" in dot      # two relations on one dependency
    assert "rank=same" in domains.to_dot(G)


def test_domains_command_prints_the_graph(built, capsys):
    main(["utils", "domains", "-o", str(built / "domains")])
    out = capsys.readouterr().out
    assert "coarsest first" in out and "repo -belongs_to-> product" in out and " nodes," in out
    assert "outside the declared" not in out                                  # every cross-domain edge is now declared
    json.loads((built / "domains" / "domains.json").read_text())


def test_hierarchy_lists_parents_before_children(built):
    G = domains.load_domain("org", built / "domains")
    rows = domains.hierarchy(G)
    assert len(rows) == G.number_of_nodes()
    depth = dict((n, d) for d, n in rows)
    for u, v, data in G.edges(data=True):
        if data["relation"] == "part_of":
            assert depth[u] == depth[v] + 1
    assert [n for d, n in rows if d == 0] == sorted(n for d, n in rows if d == 0)
    assert len(domains.hierarchy(G, limit=2)) == 2


def test_below_gives_a_product_its_repositories_files_and_relations(built):
    d = built / "domains"
    prod = "product:acme/retail/shop/checkout"
    sub = domains.below(prod, "repo", d)
    assert sub.nodes["project:acme-shop"].get("seed")                       # linked by belongs_to
    projects = {a.get("project") for _, a in sub.nodes(data=True)}
    assert projects == {"acme-shop"}                                        # nothing from rq-demo
    kinds = {a.get("kind") for _, a in sub.nodes(data=True)}
    assert {"project", "file"} <= kinds and sub.number_of_edges() > 0
    assert all(domains.node_domain(sub, n) == "repo" for n in sub)


def test_below_includes_what_is_inside_the_parent_node(built):
    d = built / "domains"
    parent = "product:acme/retail/shop"                                    # checkout is part_of shop
    inner = domains.below("product:acme/retail/shop/checkout", "repo", d)
    outer = domains.below(parent, "repo", d)
    assert set(inner.nodes) <= set(outer.nodes) and "project:acme-shop" in outer


def test_below_org_gives_products_and_loads_two_partitions(built, monkeypatch):
    d = built / "domains"
    loaded: list[str] = []
    real = domains.load_domain
    monkeypatch.setattr(domains, "load_domain", lambda name, out=None: (loaded.append(name), real(name, out))[1])
    sub = domains.below("org:acme/engineering/commerce/payments", "product", d)
    assert sub.nodes["product:acme/retail/shop"].get("seed")
    assert sorted(set(loaded)) == ["org", "product"]
    assert domains.below("org:acme/engineering/commerce/payments", "repo", d).number_of_nodes() == 0   # not adjacent
    with pytest.raises(KeyError):
        domains.below("org:nope", "product", d)
