"""Processing domain: artifact type -> processor. Each processor returns a graphify extraction dict
(plus an optional `refs` list of unresolved cross-references the pipeline resolves later)."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import time
import warnings
from pathlib import Path
from typing import Callable

import yaml

from graphify.detect import _is_ignored, _is_noise_dir, _load_graphifyignore, _parse_gitignore_line
from graphify.extract import collect_files, extract

from . import paths
from .progress import current
from .area import Processor, Project, glob_match, make_id
from .claude_import import p_claude_memory
from . import llm
from .llm import BackendLimitError, resolve_backend


def _inside(root: Path, f: Path) -> bool:
    """True if f (after following symlinks) lives under root; symlinks to other repos are skipped."""
    try:
        f.resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _ignore_patterns(project: Project) -> list[tuple[Path, str]]:
    """.graphifyignore (graphify's own) + .gitignore + the project's `ignore:` list, gitignore semantics."""
    pats = list(_load_graphifyignore(project.path))
    gi = project.path / ".gitignore"
    if gi.exists():
        pats += [(project.path, ln) for raw in gi.read_text(errors="replace").splitlines()
                 if (ln := _parse_gitignore_line(raw))]
    return pats + [(project.path, g) for g in project.area.ignore + project.ignore]


def walk_project(project: Project) -> list[Path]:
    pats, root, out = _ignore_patterns(project), project.path, []
    cache: dict = {}     # graphify memoises each folder's verdict here; without it every file re-checks all its parents
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".") and not _is_noise_dir(d) and d != "graphify-out"
                  and not _is_ignored(Path(dp) / d, root, pats, _cache=cache)]
        for f in fns:
            fp = Path(dp) / f
            if not f.startswith(".") and _inside(root, fp) and not _is_ignored(fp, root, pats, _cache=cache):
                out.append(fp)
    return sorted(out)


def _rel(project: Project, f: Path) -> str:
    try:
        return f.relative_to(project.path).as_posix()
    except ValueError:
        return f.resolve().relative_to(project.path).as_posix()


def _ids(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value))
    return [str(i).strip() for i in items if str(i).strip()]


def _empty() -> dict:
    return {"nodes": [], "edges": [], "hyperedges": [], "refs": [], "warnings": []}


_DOC_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}  # owned by the document processors, not tree-sitter


def p_ast(project: Project, files: list[Path], proc: Processor) -> dict:
    """graphify tree-sitter extraction. Uses graphify's own file discovery (ignore rules, languages)."""
    allowed = {f.resolve() for f in files}   # already filtered by ignore rules and `match`
    found = [f for f in collect_files(project.path)
             if f.suffix.lower() not in _DOC_SUFFIXES and f.resolve() in allowed]
    if not found:
        return _empty()
    base = Path(os.path.commonpath([f.parent for f in found])).resolve()
    # root pins the path anchor (graphify otherwise derives it from cache_root); cache_root keeps graphify's
    # cache out of the project and the current directory.
    chatter = io.StringIO()      # graphify prints its AST-cache statistics; a default build is quiet, so they go to the progress notes instead
    with warnings.catch_warnings(), contextlib.redirect_stdout(chatter), contextlib.redirect_stderr(chatter):
        warnings.filterwarnings("ignore", message="stat index switched")   # we use one cache root per project on purpose
        out = extract(found, cache_root=paths.cache_dir() / "ast" / project.name, root=base)
    for line in chatter.getvalue().splitlines():
        if line.strip():
            current().note(line.strip())
    out.setdefault("refs", [])
    # graphify reports paths relative to the files' common directory; make them project-relative.
    shift = base.relative_to(project.path)
    for item in out["nodes"] + out["edges"]:
        sf = item.get("source_file")
        if sf and not Path(sf).is_absolute():
            item["source_file"] = (shift / sf).as_posix()
    return out


def p_frontmatter(project: Project, files: list[Path], proc: Processor) -> dict:
    """Markdown -> one node per file. Frontmatter supplies id/title/kind/stages and relation edges."""
    out, relations = _empty(), project.area.relation_names
    for f in files:
        rel = _rel(project, f)
        text = f.read_text(encoding="utf-8", errors="replace")
        fm: dict = {}
        if text.startswith("---"):
            parts = text.split("\n---", 1)
            if len(parts) == 2:
                try:
                    loaded = yaml.safe_load(parts[0][3:])
                    fm = loaded if isinstance(loaded, dict) else {}
                except yaml.YAMLError:
                    fm = {}
        title = fm.get("title") or next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), f.stem)
        doc_id = str(fm["id"]) if fm.get("id") else None
        node = {"id": "doc_" + make_id(doc_id or rel), "label": f"{doc_id}: {title}" if doc_id else title,
                "file_type": "document", "source_file": rel, "kind": fm.get("kind", "document"),
                "stages": _ids(fm.get("stages")), "doc_id": doc_id}
        out["nodes"].append(node)
        for rname in relations:
            for target in _ids(fm.get(rname)):
                out["refs"].append({"source": ("id", node["id"]), "relation": rname, "target": target, "file": rel})
    return out


_ANNOT = re.compile(r"^\s*(?:#|//|--|/?\*+)\s*@?([A-Za-z_]+)\s*:\s*(.+?)\s*$")


def p_annotations(project: Project, files: list[Path], proc: Processor) -> dict:
    """`# verifies: REQ-001` style comments in any text file -> explicit edges from that file."""
    out, relations = _empty(), project.area.relation_names
    for f in files:
        rel = _rel(project, f)
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = _ANNOT.match(line)
            if m and m.group(1) in relations:
                for target in _ids(m.group(2)):
                    out["refs"].append({"source": ("path", rel), "relation": m.group(1), "target": target, "file": rel})
    return out


def p_llm(project: Project, files: list[Path], proc: Processor) -> dict:
    """graphify's semantic extraction prompt, five files per call, through the one LLM seam (`llm.complete`: any dd-llm backend)."""
    from graphify import llm as g
    if not files:
        return _empty()
    backend = resolve_backend(None, project.backend, proc.backend)
    out = _empty()
    for i in range(0, len(files), 5):
        prompt = g._EXTRACTION_SYSTEM + "\n\n" + g._read_files(files[i:i + 5], project.path)
        try:
            part = g._parse_llm_json(llm.complete(prompt, backend=backend))
        except BackendLimitError as e:
            out["warnings"].append(f"{e}; skipping remaining files")
            break
        except RuntimeError as e:
            out["warnings"].append(f"LLM extraction failed ({e}); batch skipped")
            continue
        for k in ("nodes", "edges", "hyperedges"):
            out[k].extend(part.get(k, []))
    return out


_ITEMS_PROMPT = """You read ONE document from a {area} project and extract its discrete work items.

Allowed item kinds: {kinds}
Allowed stages (lifecycle tags, use only these ids): {stages}
Stage meaning, in flow order: {flow}

Return ONLY a JSON object, no prose, no markdown fences:
{{"items": [{{"title": "<=100 chars", "kind": "<one allowed kind>", "stages": ["<allowed stage ids>"],
  "status": "done|open|unknown", "summary": "<=200 chars"}}]}}

Rules:
- Only items the document states explicitly: a requirement or goal, a decision taken, a task or to-do.
- Skip background, rationale, headings and anything you would have to invent. Prefer fewer, accurate items.
- status "done" only if the document marks it done (strikethrough, [x], "shipped", "done").
- At most {max_items} items.

Document path: {path}
<document>
{text}
</document>
"""
_MAX_DOC_CHARS, _MAX_ITEMS = 24_000, 40


def _cache_dir() -> Path:
    d = paths.cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _json_object(raw: str) -> dict:
    """Pull the first {...} object out of an LLM reply (tolerates fences and chatter)."""
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        out = json.loads(raw[i:j + 1])
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


_RECIPES: dict = {}


def _items_recipe(proc: Processor):
    """The recipe that extracts items for this processor (loaded once per process): its own `recipe:`, else the shipped `extract_items`;
    its own `prompt:` replaces the recipe's prompt."""
    from . import recipes
    key = (proc.recipe or "extract_items", proc.prompt)
    if key not in _RECIPES:
        _RECIPES[key] = recipes.Recipe(key[0], prompt=key[1])
    return _RECIPES[key]


def p_llm_items(project: Project, files: list[Path], proc: Processor) -> dict:
    """Area-prompted extraction: prose docs -> typed work items (INFERRED, origin=llm).

    Uses graphify's backend dispatcher (`_call_llm`) but our own prompt, built from the area pack's
    vocabulary. Results are cached by prompt hash in <home>/cache, so reruns cost nothing."""
    d, out = project.area, _empty()
    backend = resolve_backend(None, project.backend, proc.backend)
    kinds = proc.kinds or ["requirement", "decision", "task"]
    flow = "; ".join(f"{s.id}->{','.join(s.next)}" for s in d.stages.values())
    use_recipe = os.environ.get("WORKGRAPH_LLM_ITEMS", "recipe") != "python"      # "python": the old in-code path, kept until the output is proven equal
    recipe = _items_recipe(proc) if use_recipe else None
    for n, f in enumerate(files, 1):
        rel = _rel(project, f)
        text = f.read_text(encoding="utf-8", errors="replace")[:_MAX_DOC_CHARS]
        if recipe:
            inputs = {"area": d.name, "kinds": ", ".join(kinds), "stages": ", ".join(d.stages), "flow": flow,
                      "max_items": str(_MAX_ITEMS), "path": rel, "text": text}
            ident = backend + recipe.fingerprint + json.dumps(inputs, sort_keys=True)
        else:
            prompt = _ITEMS_PROMPT.format(area=d.name, kinds=", ".join(kinds), stages=", ".join(d.stages), flow=flow,
                                          max_items=_MAX_ITEMS, path=rel, text=text)
            ident = backend + prompt
        cache = _cache_dir() / f"llm_items-{hashlib.sha256(ident.encode()).hexdigest()[:24]}.json"
        if cache.exists():
            items = json.loads(cache.read_text(encoding="utf-8"))
        else:
            current().note(f"LLM {n}/{len(files)}: {rel}")
            try:
                if recipe:
                    items = _json_object(recipe.run(inputs, backend=backend)["items"]).get("items", [])
                else:
                    items = _json_object(llm.complete(prompt, backend=backend, max_tokens=4096)).get("items", [])
            except BackendLimitError as e:
                out["warnings"].append(f"{rel}: {e}; skipping remaining LLM documents (rerun later, results are cached)")
                break
            except (RuntimeError, ValueError) as e:
                out["warnings"].append(f"{rel}: LLM extraction failed ({e}); skipped")
                continue
            cache.write_text(json.dumps(items), encoding="utf-8")
        for i, it in enumerate(items[:_MAX_ITEMS]):
            if not isinstance(it, dict) or not it.get("title") or it.get("kind") not in kinds:
                continue
            nid = f"item_{make_id(rel)}_{i}"
            out["nodes"].append({
                "id": nid, "label": str(it["title"])[:100], "file_type": "concept", "source_file": rel,
                "kind": it["kind"], "stages": [x for x in _ids(it.get("stages")) if x in d.stages],
                "status": it.get("status", "unknown"), "summary": str(it.get("summary", ""))[:200], "origin": "llm"})
            out["refs"].append({"source": ("id", nid), "relation": "derived_from", "target": rel, "file": rel,
                                "confidence": "INFERRED"})
    return out


# --- GraphLang files (graph.yaml, bind.yaml, graflang.errors.yaml) as artifacts of the project

def _walk_key(obj, key):
    """Every value stored under `key` anywhere in a nested mapping/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_key(v, key)


def _shipped_error_codes() -> set[str]:
    try:
        import graphlang
        raw = yaml.safe_load((Path(graphlang.__file__).parent / "graflang.errors.yaml").read_text(encoding="utf-8")) or {}
        return {str(e["code"]) for e in raw.get("errors", []) if isinstance(e, dict) and "code" in e}
    except Exception:       # GraphLang missing or its catalogue unreadable: every code used must then be defined in the project
        return set()


KIND_WORD = {"prompts": "prompt", "procedures": "procedure", "policies": "policy", "parts": "part"}


def _is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return rel.startswith("tests/") or "/tests/" in rel or name.startswith("test_") or name.endswith(("_test.py", "_test.go", ".spec.ts", ".spec.js"))


def p_graflang(project: Project, files: list[Path], proc: Processor) -> dict:
    """GraphLang files, read as plain YAML (no GraphLang runtime needed to index them).

    nodes: `recipe` (a graph.yaml; `part` when it sits in a subfolder of a folder that holds a graph.yaml itself), `bindings` (bind.yaml), `error_code`
    (graflang.errors.yaml), `policy`, `procedure` (files a graph names), plus a `prompt` node for a prompt file that is not markdown (markdown is a document).
    edges (refs): `uses` (graph -> part), `reads_prompt`, `runs` (graph -> a tool file in `command:`), `may_add` (MUTATE catalogue), `governed_by` (policy),
    `runs_procedure`, `raises` (a part's error code -> its definition), `binds` (bind.yaml -> its graph), `verifies` (INFERRED: a test that names the recipe).
    warnings: a prompt declared but never used, a prompt file no graph names, an error code nobody defines."""
    out = _empty()
    graphs = [f for f in files if f.name.endswith(".graph.yaml")]
    graph_dirs = {f.parent for f in graphs}
    shipped, made = _shipped_error_codes(), set()

    def node(rel: str, kind: str, label: str, summary: str = "", doc_id: str | None = None, key: str | None = None) -> str:
        nid = "graf_" + make_id(key or rel)
        if nid not in made:
            made.add(nid)
            out["nodes"].append({"id": nid, "label": label, "file_type": "document", "source_file": rel, "kind": kind,
                                 "summary": summary[:200], "stages": [], **({"doc_id": doc_id} if doc_id else {})})
        return nid

    parsed: dict[Path, dict] = {}

    def load(f: Path):
        if f not in parsed:
            try:
                data = yaml.load(f.read_text(encoding="utf-8", errors="replace"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
                parsed[f] = data if isinstance(data, dict) else {}
            except yaml.YAMLError as e:
                out["warnings"].append(f"{_rel(project, f)}: not valid YAML ({str(e).splitlines()[0]})")
                parsed[f] = {}
        return parsed[f]

    def target(base: Path, value) -> tuple[Path, str] | None:
        """A path named in a graph, as (file, project-relative path); None for a named part (`cookbook:x`), a missing file, or a path outside the project."""
        if not isinstance(value, str) or ":" in value.split("/")[0] or not ("/" in value or "." in value):
            return None
        p = (base / value).resolve()
        try:
            rel = p.relative_to(project.path.resolve()).as_posix() if p.is_file() else None
        except ValueError:
            return None
        return (p, rel) if rel else None

    for f in (g for g in files if g.name == "graflang.errors.yaml"):
        rel = _rel(project, f)
        for e in load(f).get("errors") or []:
            if isinstance(e, dict) and e.get("code"):
                node(rel, "error_code", str(e["code"]), str(e.get("description", "")), doc_id=str(e["code"]), key=f"{rel}#{e['code']}")

    referenced_prompts: set[str] = set()
    walked = {_rel(project, w): w for w in walk_project(project)} if graphs else {}           # what the project's ignore rules leave
    tests = [(r, w) for r, w in walked.items() if w.suffix == ".py" and _is_test_file(r)]
    test_text: dict[str, str] = {}
    for f in graphs:
        rel, data = _rel(project, f), load(f)
        wf = data.get("workflow") if isinstance(data.get("workflow"), dict) else {}
        name = str(wf.get("name") or f.name.removesuffix(".graph.yaml"))
        is_part = f.parent.parent in graph_dirs
        ins = ", ".join(str(i.get("name")) for i in wf.get("inputs") or [] if isinstance(i, dict))
        outs = ", ".join(str(o.get("name")) for o in wf.get("outputs") or [] if isinstance(o, dict))
        desc = str(wf.get("description") or "").strip()
        me = node(rel, "part" if is_part else "recipe", name, f"{desc} (in: {ins or '-'}; out: {outs or '-'})".strip(),
                  doc_id=rel)         # refs name a graph by its path; a doc_id wins over the path slot, which graphify's own `file` node of the YAML holds
        res = data.get("resources") if isinstance(data.get("resources"), dict) else {}
        text = f.read_text(encoding="utf-8", errors="replace")
        for kind, relation in (("prompts", "reads_prompt"), ("procedures", "runs_procedure"), ("policies", "governed_by"), ("parts", "uses")):
            for rname, value in (res.get(kind) or {}).items():
                t = target(f.parent, value)
                if kind == "prompts":
                    if t:
                        referenced_prompts.add(t[1])
                    if not re.search(r"(?:prompts\.|prompt_ref:\s*['\"]?(?:prompts\.)?)" + re.escape(str(rname)) + r"\b", text):
                        out["warnings"].append(f"{rel}: prompt `{rname}` is declared but no node uses it")
                if t and t[1] not in walked:
                    continue                                   # a file the project's ignore rules skip (a build/ folder, say) is not a broken reference
                if not t:
                    if kind != "parts" or ":" not in str(value).split("/")[0]:          # a named part (`cookbook:x`) is resolved by GraphLang, not by path
                        out["warnings"].append(f"{rel}: {KIND_WORD[kind]} `{rname}` names {value!r}, which is not a file in the project")
                    continue
                if kind == "policies":
                    node(t[1], "policy", t[0].name, f"policy of {name}")
                elif kind == "procedures":
                    node(t[1], "procedure", t[0].name, f"procedure of {name}")
                elif kind == "prompts" and t[0].suffix.lower() not in _DOC_SUFFIXES:
                    node(t[1], "prompt", t[0].name, f"prompt of {name}")
                out["refs"].append({"source": ("id", me), "relation": relation, "target": t[1], "file": rel})
        for cmd in _walk_key(data, "command"):
            for part in cmd if isinstance(cmd, list) else []:
                t = target(f.parent, part)
                if t and t[1] in walked and t[0].suffix in (".py", ".sh", ".js", ".ts"):
                    out["refs"].append({"source": ("id", me), "relation": "runs", "target": t[1], "file": rel})
        for cat in _walk_key(data, "catalogue"):
            for value in (cat.values() if isinstance(cat, dict) else []):
                t = target(f.parent, value)
                if t and t[1] in walked:
                    out["refs"].append({"source": ("id", me), "relation": "may_add", "target": t[1], "file": rel})
        for err in wf.get("errors") or []:
            code = err.get("code") if isinstance(err, dict) else None
            if code and code not in shipped:
                out["refs"].append({"source": ("id", me), "relation": "raises", "target": str(code), "file": rel})
        keys = {name, f.parent.name} if not is_part else set()       # a part's folder is `build` or `check`: too common a word to infer a test from
        for trel, t in tests:
            body = test_text.setdefault(trel, t.read_text(encoding="utf-8", errors="replace"))
            if rel in body or any(f'"{k}"' in body or f"'{k}'" in body for k in keys):
                out["refs"].append({"source": ("path", trel), "relation": "verifies", "target": rel, "file": trel, "confidence": "INFERRED"})

    for f in (g for g in files if g.name.endswith(".bind.yaml")):
        rel, data = _rel(project, f), load(f)
        lim = data.get("limits") if isinstance(data.get("limits"), dict) else {}
        me = node(rel, "bindings", f.name.removesuffix(".bind.yaml") + " (bindings)", "limits: " + (", ".join(f"{k}={v}" for k, v in lim.items()) or "none"))
        twin = f.with_name(f.name.removesuffix(".bind.yaml") + ".graph.yaml")
        if twin.is_file() and _rel(project, twin) in walked:
            out["refs"].append({"source": ("id", me), "relation": "binds", "target": _rel(project, twin), "file": rel})

    for g in graphs:                                   # a prompt file in a graph's own prompts/ folder that no graph in that folder names
        d = g.parent / "prompts"
        if d.is_dir():
            mine = {t[1] for gg in graphs if gg.parent == g.parent for t in [target(g.parent, str(v)) for v in
                    ((load(gg).get("resources") or {}).get("prompts") or {}).values()] if t}
            for pf in sorted(d.iterdir()):
                if pf.is_file() and _rel(project, pf) not in mine and _rel(project, pf) not in referenced_prompts:
                    out["warnings"].append(f"{_rel(project, pf)}: prompt file that no graph in {_rel(project, g.parent)} names")
    return out


def p_arch(project: Project, files: list[Path], proc: Processor) -> dict:
    """Architecture graphs (`*.arch.yaml`, see `graf util arch2mmd`), read as plain YAML.

    nodes: `architecture` (the file) and a `component` per node of the graph (doc_id = the node's id, so code can say `# implements: <id>`; ids should be unique across the project's arch files).
    edges (refs): `contains` (architecture -> component), `requires` / `optional` / `network` between components, as the graph draws them.
    warnings: the graph's own rule violations (unknown nodes, upward edges, `requires` cycles) when GraphLang is installed to check them."""
    out = _empty()
    try:
        from graphlang.grafu.arch2mmd import validate as _validate
    except ImportError:
        _validate = None
    for f in files:
        rel = _rel(project, f)
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace"))
        except yaml.YAMLError as e:
            out["warnings"].append(f"{rel}: not valid YAML ({str(e).splitlines()[0]})")
            continue
        if not isinstance(data, dict) or data.get("arch") != 1:
            out["warnings"].append(f"{rel}: not an architecture graph (needs `arch: 1`)")
            continue
        if _validate:
            errors, _ = _validate(data)
            out["warnings"] += [f"{rel}: {e}" for e in errors]
        aid = "arch_" + make_id(rel)
        title = str(data.get("title") or data.get("name") or f.name)
        out["nodes"].append({"id": aid, "label": title, "file_type": "document", "source_file": rel, "kind": "architecture",
                             "summary": f"architecture graph of {data.get('name', f.name)}", "stages": []})
        ids: dict[str, str] = {}
        for layer in data.get("layers") or []:
            for n in [*(layer.get("nodes") or []), *[m for g in layer.get("groups") or [] for m in g.get("nodes") or []]]:
                if not isinstance(n, dict) or not n.get("id"):
                    continue
                nid = ids[n["id"]] = f"arch_{make_id(rel)}_{make_id(str(n['id']))}"
                summary = " ".join(str(x) for x in n.get("summary") or [])[:200]
                out["nodes"].append({"id": nid, "label": str(n.get("name") or n["id"]), "file_type": "document", "source_file": rel, "kind": "component",
                                     "summary": summary, "stages": [], "doc_id": str(n["id"]),
                                     **({k: n[k] for k in ("pkg", "repo", "status") if n.get(k)}),
                                     "layer": layer.get("id"), "rank": layer.get("rank", 0)})
                out["refs"].append({"source": ("id", aid), "relation": "contains", "target": str(n["id"]), "file": rel})
        for e in data.get("edges") or []:
            if isinstance(e, dict) and e.get("from") in ids and e.get("to") in ids:
                out["refs"].append({"source": ("id", ids[e["from"]]), "relation": e.get("kind", "requires"), "target": str(e["to"]), "file": rel})
    return out


REGISTRY: dict[str, Callable[[Project, list[Path], Processor], dict]] = {
    "ast": p_ast, "frontmatter": p_frontmatter, "annotations": p_annotations, "llm": p_llm,
    "llm_items": p_llm_items, "claude_memory": p_claude_memory, "graflang": p_graflang, "arch": p_arch,
}


STEP_LABELS = {"ast": "code (tree-sitter)", "frontmatter": "documents", "annotations": "annotations",
               "llm": "LLM extraction", "llm_items": "LLM extraction", "claude_memory": "Claude Code memory",
               "graflang": "GraphLang files", "arch": "architecture graphs"}


def run_processors(project: Project, *, semantic: bool = False, steps: list | None = None) -> dict:
    """Run every processor of the project's area and merge the results. `steps` collects
    (label, seconds, files) per step, for progress and timing."""
    t = time.perf_counter()
    all_files = walk_project(project)
    if steps is not None:
        steps.append(("scan files", time.perf_counter() - t, len(all_files)))
    merged = _empty()
    for proc in project.area.processors:
        if proc.use in ("llm", "llm_items") and not semantic:
            continue
        if proc.use not in REGISTRY:
            raise ValueError(f"[{project.area.name}] processor {proc.name!r} uses unknown processor {proc.use!r}")
        files = [f for f in all_files if not proc.match or glob_match(_rel(project, f), proc.match)]
        if proc.use in ("llm", "llm_items") and files:
            current().note(f"LLM extraction: {len(files)} document{'s' if len(files) != 1 else ''}, one call each (cached ones are instant) ...")
        t = time.perf_counter()
        part = REGISTRY[proc.use](project, files, proc)
        if steps is not None:
            steps.append((STEP_LABELS.get(proc.use, proc.use), time.perf_counter() - t, len(files)))
        for k in ("nodes", "edges", "hyperedges", "refs", "warnings"):
            merged[k].extend(part.get(k, []))
    return merged
