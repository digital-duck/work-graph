"""Domain file schema: vocabulary and validation for the product, org and process domains (JSON form)."""
from __future__ import annotations

import re

import networkx as nx

SCHEMA = "workgraph/2"
LEGACY_SCHEMA = "workgraph/1"      # 0.2.x: `layer:` was the key now called `domain:`


def normalize_legacy(doc) -> list[str]:
    """Read a file written by 0.2.x (`schema: workgraph/1`, `layer: org`) as the new form, in place; the notes to show (empty for a new file)."""
    if isinstance(doc, dict) and doc.get("schema") == LEGACY_SCHEMA and "layer" in doc and "domain" not in doc:
        doc["domain"] = doc.pop("layer")
        doc["schema"] = SCHEMA
        return ["written by workgraph 0.2.x (`layer:`, schema workgraph/1): read as `domain:`; run `workgraph utils migrate` to rewrite it"]
    return []

DOMAIN_KINDS = {
    "product": {"family", "product", "application"},
    "org": {"company", "division", "department", "group", "team", "person"},
    "process": {"process", "step"},
}

# id prefix -> domain; anything else is a repo-graph node
PREFIX_DOMAIN = {"org": "org", "product": "product", "process": "process", "stage": "process", "project": "repo"}

# relation -> (source domains, target domains); None means "same domain as the other end"
RELATION_RULES = {
    "part_of": None,
    "precedes": ({"process"}, {"process"}),
    "belongs_to": ({"repo"}, {"product"}),
    "owned_by": ({"product"}, {"org"}),
    "follows": ({"product"}, {"process"}),
}

# Relations the build itself adds across domains (every repo node is tagged with its stages). Not allowed
# in domain files, but part of the domain map, so the dependency between repo and process is visible.
BUILD_RELATIONS = {
    "in_stage": ({"repo"}, {"process"}),
    "participates_in": ({"repo"}, {"process"}),
}

UID_RE = re.compile(r"^[0-9a-f]{8}$")


def domain_of(node_id: str) -> str:
    prefix = node_id.partition(":")[0]
    return PREFIX_DOMAIN.get(prefix, "repo")


def check_relation(relation: str, source: str, target: str) -> str | None:
    """Error text if `relation` may not join these two IDs, else None."""
    if relation not in RELATION_RULES:
        return f"unknown relation {relation!r}; allowed: {sorted(RELATION_RULES)}"
    ls, lt = domain_of(source), domain_of(target)
    rule = RELATION_RULES[relation]
    if rule is None:
        if ls != lt or ls == "repo":
            return f"`part_of` joins nodes of one domain (product, org or process), got {ls} -> {lt}"
        return None
    if ls not in rule[0] or lt not in rule[1]:
        return f"`{relation}` must go {'/'.join(sorted(rule[0]))} -> {'/'.join(sorted(rule[1]))}, got {ls} -> {lt}"
    return None


def validate_domain(doc: dict, name: str = "domain") -> list[str]:
    """Structural validation of one domain file. References to other files are checked later, in refs."""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return [f"{name}: top level must be a mapping"]
    if doc.get("schema") != SCHEMA:
        errs.append(f"{name}: `schema` must be {SCHEMA!r}")
    domain = doc.get("domain")
    if domain not in DOMAIN_KINDS:
        errs.append(f"{name}: `domain` must be one of {sorted(DOMAIN_KINDS)}, got {domain!r}")
        return errs
    for key in ("nodes", "edges"):
        if not isinstance(doc.get(key), list):
            errs.append(f"{name}: `{key}` must be a list")
    if errs:
        return errs
    ids: set[str] = set()
    uids: set[str] = set()
    for i, n in enumerate(doc["nodes"]):
        where = f"{name}: nodes[{i}]"
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            errs.append(f"{where}: needs a string `id`")
            continue
        nid = n["id"]
        where = f"{name}: node {nid}"
        if domain_of(nid) != domain or ":" not in nid:
            errs.append(f"{where}: id must start with `{domain}:`")
        if nid in ids:
            errs.append(f"{where}: duplicate id")
        ids.add(nid)
        if n.get("kind") not in DOMAIN_KINDS[domain]:
            errs.append(f"{where}: kind {n.get('kind')!r} not allowed in domain {domain} ({sorted(DOMAIN_KINDS[domain])})")
        uid = n.get("uid")
        if uid is not None:
            if not isinstance(uid, str) or not UID_RE.match(uid):
                errs.append(f"{where}: uid must be 8 hex characters")
            elif uid in uids:
                errs.append(f"{where}: duplicate uid {uid}")
            else:
                uids.add(uid)
    for i, e in enumerate(doc["edges"]):
        where = f"{name}: edges[{i}]"
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ("source", "target", "relation")):
            errs.append(f"{where}: needs string `source`, `target` and `relation`")
            continue
        src, tgt = e["source"].removesuffix("/**"), e["target"].removesuffix("/**")
        if (msg := check_relation(e["relation"], src, tgt)):
            errs.append(f"{where} ({e['source']} -{e['relation']}-> {e['target']}): {msg}")
    parents = nx.DiGraph((e["source"], e["target"]) for e in doc["edges"]
                         if isinstance(e, dict) and e.get("relation") == "part_of")
    if parents and not nx.is_directed_acyclic_graph(parents):
        errs.append(f"{name}: `part_of` edges contain a cycle")
    return errs
