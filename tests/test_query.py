import json
from pathlib import Path

import pytest

from workgraph import query
from workgraph.cli import main
from workgraph.area import Workspace
from workgraph.pipeline import build_workspace

EX = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def built(tmp_path):
    ws = Workspace.load(EX / "workspace.yaml")
    M, _, _ = build_workspace(ws)
    docs = query.build_docs(M, query.roots_from_workspace(ws))
    return M, docs


def test_docs_hide_structure_and_carry_excerpts(built):
    M, docs = built
    assert not any(d.kind in query.HIDDEN_KINDS for d in docs)
    req = next(d for d in docs if d.label.startswith("REQ-002"))
    assert "turn a cart into an order" in req.body                      # file excerpt is indexed


def test_keyword_search_ranks_names_first_and_supports_phrases_and_prefixes(built):
    _, docs = built
    hits = [d.label for _, d in query.keyword_search(docs, "checkout")]
    assert hits[0].lower().startswith(("adr-002", "checkout")) and any("REQ-002" in h for h in hits)
    assert [d.label for _, d in query.keyword_search(docs, '"discount codes"')][0].startswith("REQ-003")
    assert query.keyword_search(docs, "chec")                           # prefix match
    assert query.keyword_search(docs, "zzzqqq") == []
    body_only = query.keyword_search(docs, "turn cart order")           # only in the file text, not the title
    assert body_only and body_only[0][1].label.startswith("REQ-002")


def test_filters(built):
    _, docs = built
    assert {d.domain for d in query.filter_docs(docs, domain="org")} == {"org"}
    assert all(d.project == "rq-demo" for d in query.filter_docs(docs, project="rq-demo"))
    assert query.filter_docs(docs, kind="team")


def test_semantic_tfidf_fallback_is_labelled(built, monkeypatch):
    _, docs = built
    monkeypatch.setattr(query, "ollama_ready", lambda: (False, "ollama is not running"))
    monkeypatch.setattr(query, "sbert_ready", lambda: (False, "sentence-transformers unavailable"))
    hits, used, note = query.semantic_search(docs, "customers paying for an order", 5)
    assert used == "tfidf" and "not embeddings" in note and "ollama is not running" in note
    assert hits and any("REQ-002" in d.label or "heckout" in d.label for _, d in hits[:3])
    with pytest.raises(RuntimeError):
        query.semantic_search(docs, "x", 5, backend="ollama")
    with pytest.raises(ValueError):
        query.semantic_search(docs, "x", 5, backend="magic")


def test_semantic_ollama_path_uses_cache(built, monkeypatch):
    import numpy as np
    from dd_embed import EmbeddingAdapter, EmbeddingResult
    _, docs = built
    calls = []

    class Fake(EmbeddingAdapter):
        def embed(self, texts, **kw):
            calls.append(len(texts))
            return EmbeddingResult(np.array([[float(len(t) % 7), float(len(t.split())), 1.0] for t in texts]), True, "ollama", "fake-embed")

    monkeypatch.setattr(query, "ollama_ready", lambda: (True, "fake-embed"))
    monkeypatch.setattr(query, "_adapter", lambda backend: Fake())
    hits, used, note = query.semantic_search(docs, "cart", 3)
    assert used == "ollama" and "fake-embed" in note and len(hits) == 3
    first = sum(calls)
    query.semantic_search(docs, "cart", 3)
    assert sum(calls) - first == 1                                       # only the query is embedded the second time


def test_embedding_backends_are_dd_embed_adapters(monkeypatch):
    monkeypatch.setenv("WORKGRAPH_EMBED_MODEL", "my-embed")
    monkeypatch.setenv("OLLAMA_HOST", "http://box:11434")
    a = query._adapter("ollama")
    assert (a.model_name, a.host) == ("my-embed", "http://box:11434")
    s = query._adapter("sbert")
    assert s.model_name == "all-MiniLM-L6-v2" and s.device == "cpu"
    monkeypatch.setenv("WORKGRAPH_EMBED_DEVICE", "cuda")
    assert query._adapter("sbert").device == "cuda"


def test_a_failed_embedding_is_an_error_not_a_silent_fallback(built, monkeypatch):
    import numpy as np
    from dd_embed import EmbeddingAdapter, EmbeddingResult
    _, docs = built

    class Broken(EmbeddingAdapter):
        def embed(self, texts, **kw):
            return EmbeddingResult(np.empty((0, 0)), False, "ollama", "m", error="boom")

    monkeypatch.setattr(query, "ollama_ready", lambda: (True, "m"))
    monkeypatch.setattr(query, "_adapter", lambda backend: Broken())
    with pytest.raises(RuntimeError, match="boom"):
        query.semantic_search(docs, "cart", 3, backend="ollama")


def test_summary_neighbors_dot_and_gaps(built):
    M, _ = built
    s = query.summary(M)
    assert set(s["domains"]) == {"repo", "process", "product", "org"} and s["projects"]["acme-shop"] > 0
    nb = query.neighbors(M, "product:acme/retail/shop")
    assert ("follows", "process:sdlc", "Software development lifecycle") in nb["out"] or any(r == "follows" for r, *_ in nb["out"])
    assert "digraph" in query.to_dot(M, "product:acme/retail/shop")
    assert any(g["message"] == "requirement has no test" for g in query.gaps_for(M))


def test_cli_status_search_show_context(tmp_path, capsys):
    main(["build", "-c", str(EX / "workspace.yaml")])
    capsys.readouterr()
    main(["status"])
    out = capsys.readouterr().out
    assert "domains:" in out and "gaps:" in out
    main(["search", "checkout", "--domain", "repo"])
    assert "Checkout" in capsys.readouterr().out
    main(["show", "REQ-002"])
    out = capsys.readouterr().out
    assert "REQ-002" in out and "kind: requirement" in out
    with pytest.raises(SystemExit):
        main(["show", "no-such-node"])
    main(["track", str(EX / "acme-shop")])
    capsys.readouterr()
    main(["utils", "context", str(EX / "acme-shop")])
    assert "memory for project acme-shop" in capsys.readouterr().out
