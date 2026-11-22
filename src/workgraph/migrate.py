"""`workgraph utils migrate`: bring a home folder and workspace files from the words of 0.2.x to those of 0.3.0.

0.3.0 renamed two things (docs/DEV/graflang-refactor.md, Phase 0b), in this order:
  1. `domain` (a pack such as sdlc) became `area`:      `domain:` -> `area:` in workspace files and packs, `custom/domains/` -> `custom/areas/`
  2. `layer` (org, product, process, repo) became `domain`: `layer:` -> `domain:` in graph files, the database column, `out/layers/` -> `out/domains/`
Every step is safe to run twice and reports what it did; `--dry-run` only reports. The loader also reads the old keys for one release, with a warning.
"""
from __future__ import annotations

import re
import json
import shutil
from pathlib import Path

import yaml

from . import paths
from .schema import LEGACY_SCHEMA, SCHEMA

FORMAT = 2     # `graph.json` written by 0.3.0 carries graph["workgraph_format"] = 2; an older file is refused with a "rebuild" message

_AREA_KEY = re.compile(r"(?m)(^|[\s{,])domain:")


def rename_area_key(text: str) -> str:
    """`domain: x` -> `area: x` in a YAML text, at the start of a line or inside a `{...}` mapping; comments and layout are kept."""
    return _AREA_KEY.sub(r"\1area:", text)


def _rewrite(path: Path, fn, dry: bool, say: list[str], what: str) -> None:
    text = path.read_text(encoding="utf-8")
    new = fn(text)
    if new != text:
        say.append(f"{what}: {path}")
        if not dry:
            path.write_text(new, encoding="utf-8")


def migrate_areas(workspaces: list[Path], dry: bool = False) -> list[str]:
    say: list[str] = []
    old, new = paths.custom_dir() / "domains", paths.custom_areas_dir()
    if old.is_dir():
        for f in sorted(old.glob("*.y*ml")):
            target = new / f.name
            if target.exists():
                say.append(f"left in place (an area pack of that name exists): {f}")
                continue
            say.append(f"moved {f} -> {target}")
            if not dry:
                new.mkdir(parents=True, exist_ok=True)
                f.rename(target)
        if not dry and not any(old.iterdir()):
            old.rmdir()
    if new.is_dir():
        for f in sorted(new.glob("*.y*ml")):
            _rewrite(f, rename_area_key, dry, say, "`domain:` -> `area:` in the area pack")
    for ws in workspaces:
        if ws.exists():
            _rewrite(ws, rename_area_key, dry, say, "`domain:` -> `area:` in the workspace file")
    return say


_LAYER_KEY = __import__("re").compile(r"(?m)^layer:")
_OLD_SCHEMA = __import__("re").compile(r"(?m)^schema:\s*" + __import__("re").escape(LEGACY_SCHEMA) + r"\s*$")


def graphs_dirs(workspaces: list[Path]) -> list[Path]:
    """The folders that hold domain files: the home's `custom/graphs/` and each workspace's own (`graphs:` key, else `graphs/` beside it)."""
    out = [paths.graphs_dir()]
    for ws in workspaces:
        if not ws.exists():
            continue
        raw = yaml.safe_load(ws.read_text(encoding="utf-8")) or {}
        out.append((ws.parent / raw["graphs"]) if raw.get("graphs") else ws.parent / "graphs")
    seen, unique = set(), []
    for d in out:
        if d.is_dir() and d.resolve() not in seen:
            seen.add(d.resolve())
            unique.append(d)
    return unique


def migrate_domains(workspaces: list[Path], dry: bool = False) -> list[str]:
    """`layer:` -> `domain:` and schema workgraph/1 -> workgraph/2 in every domain file (JSON and its YAML twin); the stale `out/layers/`."""
    say: list[str] = []
    for d in graphs_dirs(workspaces):
        for j in sorted(d.glob("*.json")):
            try:
                doc = json.loads(j.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(doc, dict) and "layer" in doc and "domain" not in doc:
                say.append(f"`layer:` -> `domain:`, schema {SCHEMA}: {j}")
                if not dry:
                    new = {("domain" if k == "layer" else k): (SCHEMA if k == "schema" and v == LEGACY_SCHEMA else v) for k, v in doc.items()}
                    j.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                y = j.with_suffix(".yaml")
                if y.exists():
                    _rewrite(y, lambda t: _OLD_SCHEMA.sub(f"schema: {SCHEMA}", _LAYER_KEY.sub("domain:", t)), dry, say, "  the YAML twin")
    stale = paths.out_dir() / "layers"
    if stale.is_dir():
        say.append(f"removed the old build output: {stale} (`workgraph build` writes out/domains/)")
        if not dry:
            shutil.rmtree(stale)
    return say


def migrate(workspaces: list[Path], dry: bool = False) -> list[str]:
    """Run every step, in order (areas first: it frees the word `domain`); the list of what was (or, with `dry`, would be) changed."""
    files = [paths.default_workspace(), *workspaces]
    seen, unique = set(), []
    for f in files:
        if f.resolve() not in seen:
            seen.add(f.resolve())
            unique.append(f)
    return migrate_areas(unique, dry) + migrate_domains(unique, dry)
