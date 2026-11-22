"""Area-rule analysis on the knowledge nodes (pure NetworkX, no LLM)."""
from __future__ import annotations

import networkx as nx

from .area import STRUCTURAL_KINDS, Workspace, glob_match


def find_gaps(M: nx.MultiDiGraph, ws: Workspace) -> list[dict]:
    """Evaluate each area's `expectations`: artifacts in a stage that lack a required relation."""
    areas, gaps = ws.areas, []
    symbols: dict[tuple, int] = {}
    for _, d in M.nodes(data=True):
        if d.get("kind") == "symbol":
            k = (d.get("project"), d.get("source_file"))
            symbols[k] = symbols.get(k, 0) + 1
    for n, d in M.nodes(data=True):
        if d.get("kind") in ("stage", "project") or d.get("area") not in areas:
            continue   # process nodes, and domain nodes (product, org, ...) that belong to no area pack
        for exp in areas[d["area"]].expectations:
            kinds = exp.get("kinds")
            if exp["stage"] not in d.get("stages", []):
                continue
            if d.get("origin") == "llm" and not exp.get("include_llm"):
                continue   # LLM-extracted items are unverified; they don't trigger gap rules by default
            if exp.get("exclude") and glob_match(d.get("source_file") or "", exp["exclude"]):
                continue
            if symbols.get((d["project"], d.get("source_file")), 0) < exp.get("min_symbols", 0):
                continue
            if (d["kind"] not in kinds) if kinds else (d["kind"] in STRUCTURAL_KINDS):
                continue
            edges = M.in_edges(n, data=True) if exp.get("direction", "in") == "in" else M.out_edges(n, data=True)
            if not any(e.get("relation") == exp["needs"] for *_, e in edges):
                gaps.append({"node": n, "label": d.get("label", n), "project": d["project"], "area": d["area"],
                             "stage": exp["stage"], "needs": exp["needs"], "message": exp["message"],
                             "source_file": d.get("source_file")})
    return sorted(gaps, key=lambda g: (g["area"], g["message"], g["label"]))
