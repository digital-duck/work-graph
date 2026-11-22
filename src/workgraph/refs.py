"""Domain files -> the in-memory graph. References (including `/**` sub-graph references) are resolved here,
so everything downstream sees one NetworkX graph whose nodes carry a `domain` attribute."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import networkx as nx

from .area import Workspace
from .schema import domain_of, normalize_legacy, validate_domain
from .store import Store, file_key, sha256

GLOB = "/**"


def domain_files(graphs_dir: Path) -> list[Path]:
    return sorted(graphs_dir.glob("*.json"))


def load_domains(graphs_dir: Path) -> tuple[dict[str, dict], list[str]]:
    """Read and validate every JSON domain file. Returns ({file name: doc}, errors). Invalid files are skipped."""
    docs: dict[str, dict] = {}
    errs: list[str] = []
    for p in domain_files(graphs_dir):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errs.append(f"{p.name}: invalid JSON ({e})")
            continue
        errs += [f"{p.name}: {n}" for n in normalize_legacy(doc)]
        found = validate_domain(doc, p.name)
        if found:
            errs += found
        else:
            docs[p.name] = doc
    return docs, errs


def _same_content(y: Path, j: Path) -> bool:
    """True if the YAML holds exactly the graph in the JSON (comments and layout aside)."""
    from ruamel.yaml import YAML
    try:
        return json.loads(json.dumps(YAML(typ="safe").load(y.read_text(encoding="utf-8")))) == json.loads(j.read_text(encoding="utf-8"))
    except Exception:
        return False


def stale_notes(graphs_dir: Path, store: Store | None = None) -> list[str]:
    """YAML files the loader will not see: no JSON counterpart, or edited after the last convert.
    The store's recorded hashes decide when it has them; otherwise file times are compared."""
    notes = []
    for y in sorted(graphs_dir.glob("*.yaml")):
        j = y.with_suffix(".json")
        reg = store.registered(file_key(y)) if store else None
        if not j.exists():
            notes.append(f"{y.name}: no {j.name}; run `workgraph utils convert {y.name}`")
        elif reg:
            if sha256(y) != reg[1]:
                notes.append(f"{y.name}: edited since the last convert; run `workgraph utils convert {y.name}`")
        elif y.stat().st_mtime > j.stat().st_mtime and not _same_content(y, j):
            notes.append(f"{y.name}: newer than {j.name}; run `workgraph utils convert {y.name}`")
    return notes


def missing_uids(docs: dict[str, dict]) -> list[str]:
    return [f"{name}: node {n['id']} has no uid" for name, d in docs.items() for n in d["nodes"] if not n.get("uid")]


def assign_uids(graphs_dir: Path) -> int:
    """Write a fresh uid into every domain node that lacks one. Edits the JSON files in place."""
    count = 0
    docs, _ = load_domains(graphs_dir)
    taken = {n["uid"] for d in docs.values() for n in d["nodes"] if n.get("uid")}
    for name, doc in docs.items():
        changed = False
        for n in doc["nodes"]:
            if not n.get("uid"):
                while (uid := secrets.token_hex(4)) in taken:
                    pass
                taken.add(uid)
                n["uid"] = uid
                count += 1
                changed = True
        if changed:
            (graphs_dir / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return count


def _descendants(parents: nx.DiGraph, node: str) -> list[str]:
    """`node` plus everything below it, following part_of edges (child -> parent) backwards."""
    if node not in parents:
        return [node]
    return [node, *sorted(nx.ancestors(parents, node))]


def _rename_hint(missing: str, store: Store | None, current: dict[str, str]) -> str:
    if store:
        for uid in store.uids_for(missing):
            if uid in current and current[uid] != missing:
                return f" (renamed to {current[uid]}: update the reference)"
    return ""


def add_process_templates(M: nx.MultiDiGraph, ws: Workspace) -> None:
    """Every area pack is a process template: `process:<area>` with its stages `part_of` it."""
    for name, dom in ws.areas.items():
        pid = f"process:{name}"
        M.add_node(pid, label=dom.label, kind="process", domain="process", stages=[], source_file=f"areas/{name}.yaml")
        for s in dom.stages:
            M.add_edge(dom.stage_node(s), pid, relation="part_of", confidence="EXTRACTED")


def merge_domains(M: nx.MultiDiGraph, ws: Workspace, store: Store | None = None) -> list[str]:
    """Add process templates and the domain files to the build graph. Returns problems as warnings."""
    for _, d in M.nodes(data=True):
        d.setdefault("domain", "process" if d.get("kind") == "stage" else "repo")
    add_process_templates(M, ws)
    if not ws.graphs_dir or not ws.graphs_dir.is_dir():
        return []
    docs, problems = load_domains(ws.graphs_dir)
    problems += stale_notes(ws.graphs_dir, store)

    owner: dict[str, str] = {}
    for name, doc in docs.items():
        for n in doc["nodes"]:
            if n["id"] in owner or M.has_node(n["id"]):
                problems.append(f"{name}: node {n['id']} is already defined in {owner.get(n['id'], 'the build graph')}")
            else:
                owner[n["id"]] = name
    known = lambda i: i in owner or M.has_node(i)  # noqa: E731
    current_uid = {n["uid"]: n["id"] for d in docs.values() for n in d["nodes"] if n.get("uid")}

    parents = nx.DiGraph()
    for u, v, d in M.edges(data=True):
        if d.get("relation") == "part_of":
            parents.add_edge(u, v)
    for doc in docs.values():
        parents.add_edges_from((e["source"], e["target"]) for e in doc["edges"] if e["relation"] == "part_of")

    for name, doc in docs.items():
        for n in doc["nodes"]:
            if n["id"] in owner and owner[n["id"]] == name:
                attrs = {"label": n["id"], **{k: v for k, v in n.items() if k != "id"},
                         "domain": doc["domain"], "source_file": f"graphs/{name}", "stages": []}
                M.add_node(n["id"], **attrs)
        for e in doc["edges"]:
            ends = []
            for end in (e["source"], e["target"]):
                base = end.removesuffix(GLOB)
                if not known(base):
                    problems.append(f"{name}: broken reference {end}{_rename_hint(base, store, current_uid)}")
                    break
                ends.append(_descendants(parents, base) if end.endswith(GLOB) else [base])
            else:
                attrs = {k: v for k, v in e.items() if k not in ("source", "target")}
                attrs.setdefault("confidence", "EXTRACTED")
                for u in ends[0]:
                    for v in ends[1]:
                        M.add_edge(u, v, **attrs)
    if store:
        for doc in docs.values():
            store.remember_ids(doc["domain"], doc["nodes"])
    return problems


def domain_summary(M: nx.MultiDiGraph) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, d in M.nodes(data=True):
        out[d.get("domain", "repo")] = out.get(d.get("domain", "repo"), 0) + 1
    return out


__all__ = ["merge_domains", "load_domains", "domain_summary", "domain_of"]
