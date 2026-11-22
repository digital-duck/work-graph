"""The deterministic part of `ask` (SOLVE nodes, backend: subprocess): find the graph facts for a question, check that an answer cites them, write the report.

stdin   {"mode": "context", "question", "keywords": the model's reply, "graph": path to graph.json, "semantic": "yes"|"no", "max_nodes": "40"}
          -> {"ok": true, "text": the facts, "ids": [node ids in the facts], "seeds": [...]}   or {"ok": false, "error": ...} when no node matches
        {"mode": "verify", "answer": text, "context": the context result}
          -> {"ok": true, "cited": [ids]}   or   {"ok": false, "error": what is wrong, in words a model can act on}
        {"mode": "report", "answer": text, "context": the context result, "verdict": the last verify result ("" when nothing was asked)}
          -> {"text": the report, "status": "grounded" | "ungrounded" | "empty"}
stdout  one line of JSON.

An answer is *grounded* only if it cites at least one node id and every id it cites is one of the facts it was given. Anything else is reported as
UNGROUNDED, with the reason, and the report says not to rely on it. The model never decides which of the two a report is.
"""
import json
import re
import sys

CITE = re.compile(r"\[([^\[\]\n]{2,200})\]")
NEIGHBOURS_PER_SEED = 8


def load(graph):
    from workgraph import query
    return query, query.load_graph(graph or None)


def context(job):
    query, M = load(job.get("graph"))
    docs = query.build_docs(M)
    words = str(job.get("keywords") or "").replace(",", " ")
    q = (words + " " + str(job.get("question", ""))).strip()
    hits = [d for _, d in query.keyword_search(docs, q, 6)]
    if str(job.get("semantic", "no")).lower() in ("yes", "true", "1"):
        try:
            more, _, _ = query.semantic_search(docs, str(job.get("question", "")), 6, "auto")
            hits += [d for _, d in more if d.id not in {h.id for h in hits}][:4]
        except Exception:     # no embeddings available: keyword hits stand
            pass
    if not hits:
        return {"ok": False, "error": "no node of the graph matches the question"}
    limit = int(job.get("max_nodes") or 40)
    hidden = query.HIDDEN_KINDS
    seeds = [d.id for d in hits]
    ids = list(dict.fromkeys(seeds))
    for s in seeds:
        near = sorted({v for _, v, _ in M.out_edges(s, data=True)} | {u for u, _, _ in M.in_edges(s, data=True)})
        for n in [n for n in near if M.nodes[n].get("kind") not in hidden][:NEIGHBOURS_PER_SEED]:
            if n not in ids and len(ids) < limit:
                ids.append(n)
    lines = []
    for n in ids:
        d = M.nodes[n]
        facts = ", ".join(str(x) for x in (d.get("kind"), d.get("domain"), d.get("project"), "stages " + "/".join(d["stages"]) if d.get("stages") else "",
                                           "status " + str(d["status"]) if d.get("status") else "", d.get("source_file")) if x)
        summ = f": {str(d['summary'])[:160]}" if d.get("summary") else ""
        lines.append(f"[{n}] {d.get('label', n)} ({facts}){summ}")
    inside = set(ids)
    edges = sorted({(u, d.get("relation", ""), v) for u, v, d in M.edges(data=True) if u in inside and v in inside and u != v})
    lines += [f"[{u}] --{r}--> [{v}]" for u, r, v in edges]
    return {"ok": True, "text": "\n".join(lines), "ids": ids, "seeds": seeds}


def verify(answer, ctx):
    ids = set((ctx or {}).get("ids") or [])
    cited = list(dict.fromkeys(m.strip() for m in CITE.findall(str(answer))))
    known = [c for c in cited if c in ids]
    unknown = [c for c in cited if c not in ids]
    if unknown:
        return {"ok": False, "error": "it cites ids that are not in the graph facts: " + ", ".join(unknown), "cited": known}
    if not known:
        return {"ok": False, "error": "it cites no node id; every claim must cite the ids it rests on, in square brackets", "cited": []}
    return {"ok": True, "cited": known}


def report(job):
    ctx, verdict, answer = job.get("context") or {}, job.get("verdict") or {}, str(job.get("answer") or "").strip()
    if not ctx.get("ok"):
        return {"status": "empty", "text": "The graph holds nothing that matches this question (" + str(ctx.get("error", "no node matched")) +
                "). Try `workgraph search`, or build with `--semantic`; no model answer was given, because it would not come from the graph."}
    if verdict.get("ok"):
        return {"status": "grounded", "text": answer + "\n\nGrounded in: " + ", ".join(verdict.get("cited", []))}
    return {"status": "ungrounded", "text": "UNGROUNDED: the model's answer is not backed by the graph (" + str(verdict.get("error", "not checked")) +
            "). Do not rely on it.\n\n" + answer}


def main():
    job = json.loads(sys.stdin.read() or "{}")
    mode = job.get("mode")
    if mode == "context":
        out = context(job)
    elif mode == "verify":
        out = verify(job.get("answer", ""), job.get("context"))
    elif mode == "report":
        out = report(job)
    else:
        out = {"error": f"unknown mode {mode!r}"}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
