"""GraphLang recipes shipped with workgraph, and the one function that runs them.

A recipe is a folder `<name>/<name>.graph.yaml` (prompts and tools beside it). A user can replace a shipped recipe, or add one, by putting a
folder of that name in `<home>/custom/recipes/`; the custom one wins. Every model call a recipe makes goes through `workgraph.llm.complete`
(the same seam, backends and billing rules as every other call), never through GraphLang's own adapter code.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .. import llm, paths

SHIPPED = Path(__file__).parent


class SeamLLM:
    """What GraphLang calls to reach a model (`generate`), answered by `workgraph.llm.complete` for one backend."""

    default_model = None
    model_override = None

    def __init__(self, backend: str, max_tokens: int = 4096):
        self.name = self.adapter_name = backend
        self.backend, self.max_tokens = backend, max_tokens

    def generate(self, prompt: str, model: str | None = None, **opts) -> str:
        return llm.complete(prompt, backend=self.backend, max_tokens=self.max_tokens)


def recipe_path(name: str) -> Path:
    """The graph file of a recipe: the user's `custom/recipes/<name>/` first, else the shipped one."""
    for root in (paths.custom_dir() / "recipes", SHIPPED):
        p = root / name / f"{name}.graph.yaml"
        if p.exists():
            return p
    raise FileNotFoundError(f"no recipe named {name!r} (looked in {paths.custom_dir() / 'recipes'} and {SHIPPED})")


class Recipe:
    """A loaded recipe, run once per input set. Loading (YAML, schema check) happens once; each run works on a copy."""

    def __init__(self, name: str, prompt: str | None = None):
        from graphlang.grafr.bindings import bind_graph
        from graphlang.grafr.runtime import load_graph
        self.name, self.path = name, recipe_path(name)
        self._graph = load_graph(self.path)
        self.fingerprint = _fingerprint(self.path.parent, prompt_path(prompt) if prompt else None)
        if prompt:       # a processor's own prompt file replaces the recipe's first prompt (by name in its `resources.prompts`)
            found = prompt_path(prompt)
            if not found:
                raise FileNotFoundError(check_prompt(prompt))
            target = next(iter(self._graph.get("resources", {}).get("prompts", {})), None)
            if not target:
                raise ValueError(f"recipe {name!r} has no prompt to replace")
            self._graph, _ = bind_graph(self._graph, {"resources": {"prompts": {target: str(found)}}})

    def run(self, inputs: dict, *, backend: str, max_llm_calls: int | None = 2, max_tokens: int = 4096) -> dict:
        """Run the recipe on `inputs` and return its outputs. A model call is capped (`limits.max_llm_calls`); a backend limit
        (`llm.BackendLimitError`) is not caught here."""
        from graphlang.grafr.metering import MeteredLLM
        from graphlang.grafr.runtime import GraphLangRuntime
        model = MeteredLLM(SeamLLM(backend, max_tokens), max_llm_calls, None)
        rt = GraphLangRuntime(copy.deepcopy(self._graph), llm=model, adapter=backend, verbose=False)
        return rt.execute(inputs)


def _fingerprint(folder: Path, prompt: Path | None) -> str:
    """A hash of everything a recipe is made of (its files, and the processor's own prompt): the cache of model replies is keyed on it."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(f.relative_to(folder).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    if prompt:
        h.update(b"prompt\0" + prompt.read_bytes())
    return h.hexdigest()[:16]


def prompt_path(name: str) -> Path | None:
    """A processor's own prompt file: an absolute path, or a name in `<home>/custom/prompts/`; None when there is no such file."""
    p = Path(name).expanduser()
    if not p.is_absolute():
        p = paths.custom_dir() / "prompts" / name
    return p if p.is_file() else None


def check_prompt(name: str) -> str | None:
    return None if prompt_path(name) else f"prompt file {name!r} not found (looked for it as a path and in {paths.custom_dir() / 'prompts'})"


def check_recipe(name: str) -> str | None:
    """Offline check of a recipe name for `validate-pack`: it exists and `graf validate` would accept it. None when fine."""
    try:
        path = recipe_path(name)
    except FileNotFoundError as e:
        return str(e)
    try:
        from graphlang.grafr.runtime import load_graph
        g = load_graph(path)
    except Exception as e:      # a schema or structure error: the message says which
        return f"recipe {name!r} does not load: {e}"
    names = {i["name"] for i in g["workflow"].get("inputs", [])}
    need = set(INTERFACE["inputs"]) - names
    outs = {o["name"] for o in g["workflow"].get("outputs", [])}
    if need or INTERFACE["output"] not in outs:
        return f"recipe {name!r} must take the inputs {INTERFACE['inputs']} and give the output {INTERFACE['output']!r}" + (f" (missing inputs: {sorted(need)})" if need else "")
    return None


INTERFACE = {"inputs": ["area", "kinds", "stages", "flow", "max_items", "path", "text"], "output": "items"}
