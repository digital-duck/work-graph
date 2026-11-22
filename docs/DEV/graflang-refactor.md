# Refactoring work-graph with GraphLang (plan)

Date: 2026-11-22
Status: plan, decisions recorded in section 8. **Phases 0b (the rename), 1 (the LLM seam) and 2 (`llm_items` as a recipe) and 3 (`workgraph ask`) are done** (2026-11-22, commits `1e15f42` and `0ed9099`); the other phases are not started. Nothing here is done. Written after reading the work-graph tree (`CLAUDE.md`, `README.md`, `pipeline.py`, `processors.py`,
`llm.py`, `cc_cli.py`, `query.py`, `pyproject.toml`) and the parts of GraphLang and dd-llm it would touch. What was read and what was not is
marked; "verify" means a step the plan depends on but nobody has checked yet.

## 1. What work-graph is today

A thin layer over graphify (`graphifyy`) that builds a NetworkX knowledge graph of projects, the software lifecycle and the knowledge around it, adapted
per domain pack (YAML). About 4,400 lines in `src/workgraph/` (the biggest: `cli.py` 677, `syncing.py` 392, `query.py` 322, `domain.py` 296, `processors.py` 292),
about 90 tests, version 0.2.0 on PyPI.

Where a model is involved today, and only here:

| Place | What it does |
|---|---|
| `processors.p_llm_items` | one model call per prose document: a domain-pack-built prompt (`_ITEMS_PROMPT`, a Python string in `processors.py`), reply parsed by `_json_object`, cached in `<home>/cache` by prompt hash |
| `processors.p_llm` | graphify's own extraction prompt, five files per call, through `llm.complete` |
| `llm.py`, `cc_cli.py` | one seam: backend resolution (argument, `WORKGRAPH_BACKEND`, project, pack, default `cc_cli`), billing notes, readiness checks; `cc_cli` is a port of SPL.py's `claude_cli` adapter (strips API-key variables so the call bills the subscription, retries launch failures, raises `BackendLimitError`) |
| `ask` | **not built** (README MVP list: "seed, expand, LLM answer with cited nodes") |

Everything else is deterministic Python on NetworkX objects: the processors `ast`, `frontmatter` and `annotations`, tagging, reference resolution, flow edges,
clustering, the merge of the domain graphs (org, product, process, repo), search, sync, the Streamlit UI, the hooks.

## 2. Where GraphLang fits, and where it does not

GraphLang is for workflows where a model and exact tools alternate and the shape of the work matters (prompts as files, validation before a run, call caps,
logs, error exits, a picture). It is not a replacement for ordinary code that moves graph objects around: a graph's ports carry text and JSON, not NetworkX
graphs.

| Area | Verdict | Why |
|---|---|---|
| LLM backend seam (`llm.py`, `cc_cli.py`) | **replace with dd-llm** | dd-llm's `claude_cli` already strips `ANTHROPIC_API_KEY` and the nested-session variables, and marks a session or quota limit (`error_type == "ModelOverloaded"`); dd-llm also has `bedrock`, `anthropic`, `gemini`, `vertex`, `ollama`/OpenAI-compatible. `cc_cli.py` duplicates it |
| `llm_items` extraction | **make it a GraphLang recipe** | a prompt, a call, a parse, a check of the result against the pack's vocabulary: exactly a small recipe; the prompt becomes a file the pack can override |
| `ask` (unbuilt) | **build it as a recipe, not as hand-written Python** | question, search, expand, answer with cited ids, check the ids exist: model and exact steps alternating, with a clear failure path |
| GraphLang files as artifacts in the knowledge graph | **new processor** | work-graph can then answer "which recipes use this prompt or part", and gap rules apply to recipes |
| `p_llm` (graphify's prompt, batches of 5) | route its call through dd-llm; keep graphify's prompt | the prompt is graphify's; a recipe adds nothing |
| Build pipeline (`pipeline.py`), `ast`/`frontmatter`/`annotations`, the domain graphs (`layers.py`, `refs.py`), store, sync, convert | **leave as Python** | deterministic, object-heavy, no model |
| Hooks (`claude_code.py`) | **leave** | must never raise or block; a runtime start-up is the wrong cost in a session hook |
| Streamlit UI, `viz` | **leave** | already on zinet, as GraphLang is |
| `query.py` embeddings (ollama, sbert, TF-IDF) | **later: consider dd-embed** | GraphLang's recipe search already uses dd-embed; the two implementations duplicate each other. Medium value, check parity first |

## 3. Plan, in order

Each phase is one or more commits, the whole suite green before and after, and `examples/` untouched (their gaps are deliberate; tests rely on them).

### Phase 0: groundwork

- Run the baseline (`python -m pytest` in the `graf` conda env) and record the result.
- Add `dd-llm` and `graflang` to `pyproject.toml` as core dependencies (decided, section 8; `dd-llm` is only mentioned in the setup docs today).
- The rename of Phase 0b comes before everything else, so the later phases are written in the new words.

### Phase 0b: the rename (DONE 2026-11-22: `1e15f42` domain -> area, `0ed9099` layer -> domain)

Two renames, **in this order** (the second needs the first to free the word "domain"), each its own commit with the suite green:

1. **`domain` becomes `area`** for what is now the domain pack (`sdlc`, `research`, `publishing`): `domain.py` -> `areas.py`, `src/workgraph/domains/` -> `areas/`, `custom/domains/` -> `custom/areas/`, `workgraph utils domains` -> `utils areas`, `validate-pack` keeps its name (it validates an area pack), the node field `domain` -> `area`, the `domain:` key of each project in `workspace.yaml` -> `area:`, `tests/test_domains.py`. About 25 files use the word (`domain.py` 30 lines, `cli.py` 20, `pipeline.py` 15, `USER-GUIDE.md` 18).
2. **`layer` becomes `domain`** for the org, product, process and repo graphs: `layers.py` -> `domains.py`, `schema.py` (`LAYER_KINDS`, `layer_of`, `validate_layer`), `refs.py`, `store.py`, the `layer` key of each graph file (`"layer": "org"` -> `"domain": "org"`) and the node field `layer`, `<out>/layers/` -> `<out>/domains/`, the Layers tab of the UI, `tests/test_layers.py`, `tests/test_layer_graph.py`. About 24 files (`README-design.md` 84 lines, `layers.py` 80, `app.py` 46, `cli.py` 36).

What needs a migration, because work-graph 0.2.0 is on PyPI and people have homes:
- **Graph files and `workspace.yaml`:** the loader accepts the old keys (`layer:`, `domain:`) for one release and warns once; `workgraph utils convert` and a new `utils migrate` rewrite them; the schema string goes from `workgraph/1` to `workgraph/2`.
- **The home folder:** `init_home` moves `custom/domains/` to `custom/areas/` (it already moves the old `<home>/graphs/`), as it did before.
- **The database (`workgraph.sqlite3`):** the tables `files` and `node_ids` have a `layer` column; rename the column on open (SQLite `ALTER TABLE ... RENAME COLUMN`), **verify** on a copy of a real home first.
- **`out/graph.json`** is rebuilt by `workgraph build`; no migration, but the loader refuses a pre-rename file with a clear "rebuild" message.
- **Sync (`syncing.py`):** a home synced from another machine at the old version must not be half-migrated; the sync check should compare the schema string and refuse a mismatch.
- **Docs and the plugin text:** `README.md`, `CLAUDE.md`, `docs/GUIDE/*`, `docs/DEV/README-design.md` (the word "layered graph", used in `CLAUDE.md`, becomes "graph of domains"; GraphLang's "layer" stays its own), the `/workgraph` command text (`src/workgraph/data/workgraph-command.md`, which must stay identical to `plugin/commands/workgraph.md`; a test checks).
- **Acceptance:** before and after each rename the same `workgraph build` on `examples/` gives the same graph apart from the renamed fields (diff the two `graph.json` files with the fields mapped), and the suite passes. A mechanical rename is easy to get 95% right and then break a docstring or a test fixture, so do each step with a search for the old word left over (case-insensitive, in code, tests, docs, YAML), and read the remaining hits.

**Result of Phase 0b** (what was done, what was checked, what was not):

- Both renames are in, in order, one commit each: code, files and folders (`area.py`, `areas/`, `domains.py`, `custom/areas/`), CLI (`utils areas`, `utils domains` now shows the domain map, `--area`, `viz --domain`), UI (the Domains tab), docs, the plugin text, the examples (`schema: workgraph/2`), and a CHANGELOG entry. The schema string is `workgraph/2`; `graph.json` carries `workgraph_format: 2`.
- `workgraph utils migrate [-c FILE] [--dry-run]` rewrites workspace files, area packs, graph files (JSON and the YAML twin, comments kept) and drops the old `out/layers/`; it is safe to run twice. The loaders also read the old keys for one release with a warning, `init_home` moves `custom/domains/`, the database columns are renamed on open, a sync record from 0.2.x is accepted, and a `graph.json` from 0.2.x is refused with "run `workgraph build` again" (the session hook rebuilds in the background instead).
- **Checked:** 9 new tests; the suite is at 92 passing and the same 5 failures it had before the work (the `acme-shop` example now has 31 nodes where tests expect 26, graphify prints an "AST cache" line the progress tests do not expect, and a UI count: all unrelated to the rename). An end-to-end run: a home built by the 0.2.x code (custom pack, workspace file, three graph files, a database), opened by the new code (warnings only), migrated, rebuilt: the same 49 nodes and 119 edges, and the only difference is `source_file` of the 7 stage nodes (`domains/sdlc.yaml` -> `areas/sdlc.yaml`).
- **Not done, on purpose:** (1) the sync check does **not** refuse a tree from a machine on the old version, as the plan first said; it reads the old files and records and warns, which is gentler and loses nothing. Say so if you want the refusal. (2) The build graph's own "process layer" and "knowledge nodes" (the stage and project hub nodes versus the artifacts; `knowledge_nodes()`, `README.md`, `CLAUDE.md`) keep the word "layer": it is a third use of it, not the org, product, process and repo graphs. See question 7. (3) Nothing was run on a real user home; `workgraph claude-setup` and the plugin text were not run.
- The suite needs `PYTHONPATH=src` in the `graf` env (workgraph is not installed there; installing it would pull in PyTorch).

### Phase 1: one LLM seam, dd-llm (DONE 2026-11-22)

- `llm.complete(prompt, backend=...)` calls `dd_llm.get_adapter(backend)` for every backend; `cc_cli.py` goes away (or shrinks to a compatibility alias).
- Keep what users see: the resolution order (argument, `WORKGRAPH_BACKEND`, project `backend:`, pack `backend:`, default `cc_cli`), the names `cc_cli`, `bedrock` and so on (map `cc_cli` to dd-llm's `claude_cli`), `BILLING`, `check_backend`, and the stop-with-a-warning behaviour on a limit (`BackendLimitError` becomes a check of the failure's `error_type`).
- Keep `WORKGRAPH_CC_MODEL` and `WORKGRAPH_CC_TIMEOUT`; **verify** that dd-llm's `claude_cli` takes a model and a timeout the same way, and keeps `--tools ""` and the launch retries. If something is missing, fix it in dd-llm (shared with GraphLang and SPL.py), not in work-graph.
- Tests: `test_cc_cli.py` moves to the dd-llm path; the rest stay as they are (they patch `graphify.llm._call_llm` and the adapter).
- Acceptance: a `--semantic` build on `examples/acme-shop` gives the same nodes as before for the same model replies (use a stub adapter).

**Result of Phase 1:**

- `llm.complete()` calls `dd_llm.get_adapter(...)` for every backend; `cc_cli.py` is deleted; `dd-llm>=0.2.0` is a core dependency (the `bedrock` extra is `dd-llm[bedrock]`). `p_llm` no longer has a second path through graphify's `extract_files_direct`: it runs graphify's extraction prompt, five files a call, through the seam for every backend.
- **Parity check on dd-llm's `claude_cli`:** model, timeout, `--tools ""`, launch retries (3 tries, no retry on a timeout) and stdin were already the same; a limit is `error_type == "ModelOverloaded"` (mapped to `BackendLimitError`). **One gap, fixed in dd-llm** (commit `c9e29f7`, with a test): it stripped four billing variables where work-graph stripped eight; it now strips `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY` too, and exports `STRIP_VARS`, `subscription_env()`, `stripped_vars_present()`. dd-llm also runs a tool-less call in an empty folder, which is better than before.
- **Behaviour changes** (all in the CHANGELOG): `claude-cli` now means `cc_cli` (subscription-safe; graphify's own name billed the API when a key was set); `kimi` is gone (no dd-llm adapter); an image given to `use: llm` goes in as text, as it already did under `cc_cli` (graphify's direct path sent pixels to vision backends); new `WORKGRAPH_MODEL`, the old model variables still work.
- **Checked:** `tests/test_cc_cli.py` became `tests/test_llm.py` (subprocess-level: stdin, tools off, stripped variables, model and timeout from the environment, a limit stops without retry, launch retry but no timeout retry, the `echo` adapter); the stubbed `--semantic` test gives the same items; one real haiku call through `cc_cli` answered; `utils show-llm` runs. Suite: 101 pass, none fail.

### Phase 2: `llm_items` as a recipe (DONE 2026-11-22)

- `src/workgraph/recipes/extract_items/`: `extract_items.graph.yaml`, `prompts/extract.md` (today's `_ITEMS_PROMPT`, with the domain, kinds, stages and flow as inputs), a small parse-and-check tool (the existing `_json_object` plus a filter to allowed kinds and stages), error exit `limit` for a quota stop. Shipped as package data (`package-data` in `pyproject.toml`).
- `p_llm_items` runs it per document through `graphlang.grafr.runtime` with `limits.max_llm_calls`, and keeps the **cache** itself (keyed by backend and prompt hash, as now), so a rerun still costs nothing. **Customization (decided):** a domain pack's processor may name its own prompt file (`prompt:`) or its own recipe (`recipe:`), and a user's `custom/` folder in the home folder can hold both, looked up by name and overriding the shipped ones, as `custom/domains/` already does for packs. The shipped prompt and recipe are the defaults. A custom recipe must keep the interface (inputs: the document, the domain pack's name, kinds, stages and flow; output: the items JSON text); `workgraph utils validate-pack` checks the names and `graf validate` the recipe.
- **Must handle:** GraphLang writes `.graf/` (outputs, nodes) beside the graph by default; inside an installed package that is a read-only folder. Run with the outputs switched off or redirected to `<home>/cache` (the CLI has `--no-output --no-save-nodes`; the library call needs the same, **verify**), and log through the existing progress object, not a new log folder.
- **Measure before switching:** start-up cost of building the runtime per document. If it is not negligible, build it once per project and run the graph once per document (or with a `BATCH` node). Keep the old Python path behind an environment switch until the output matches on `acme-shop` and `rq-demo`.
- Tests: a scripted-model test of the recipe (GraphLang's tests show the pattern: a small object with `generate(prompt)` answering by what the prompt asks), including a reply with chatter around the JSON, an unknown kind, and a limit.

**Result of Phase 2:**

- `src/workgraph/recipes/extract_items/` (graph, `prompts/extract.md`, `tools/parse_items.py`) and `recipes/__init__.py` (`Recipe`: load once, deep-copy and run per document; `SeamLLM`: the model GraphLang calls is `llm.complete`, so billing rules, backends and `BackendLimitError` are the same as everywhere; `recipe_path`, `check_recipe`, `check_prompt`). Shipped as package data. `graflang>=0.2.1` is a core dependency.
- **Measured:** loading the graph takes 0.2 s once per process; a run on a loaded graph takes 27 ms including the parser subprocess, against several seconds for the model call. So no batching, and no per-project runtime.
- **Handled:** no `.graf/` or log folder is written (the library call has no `RunOutput` unless given one, and logging is off until `setup_logging`); a backend limit passes through the runtime unchanged and still stops the pass with the same warning; `limits.max_llm_calls` is 2 per document.
- **Customization (decided in Q3):** processor keys `prompt:` and `recipe:`, folders `<home>/custom/prompts/` and `<home>/custom/recipes/` (a folder there wins over the shipped one); `validate-pack` checks the names and that a recipe loads and has the interface.
- **Prompt placeholders** in a prompt file are `{{in_<name>}}` (a GraphLang rule: the port name), not `{{name}}`. The document text is the last input, so a document that itself contains `{{in_path}}` is not expanded (tested).
- **Checked:** the recipe's prompt is byte-identical to the old `_ITEMS_PROMPT` output; scripted replies (chatter and a fence around the JSON, an unknown kind, an unknown stage, a non-mapping item, no JSON at all, a limit) give the same nodes on both paths; the cache serves a rerun; a custom recipe and a custom prompt win. A real haiku run on `acme-shop` through each path gave 37 nodes and 6 items each (the wording of items differs between two model calls, as it always does). 110 tests pass.
- **Left:** `WORKGRAPH_LLM_ITEMS=python` and `_ITEMS_PROMPT` stay until you say the output is proven (remove them in one small commit). The cache key changed, so the first `--semantic` build after the upgrade re-extracts once. `rq-demo` was not run for real (its only LLM processor is `llm` on PDFs, not `llm_items`).

### Phase 3: `workgraph ask` (DONE 2026-11-22)

- A recipe `src/workgraph/recipes/ask/`: `understand` (the question, as keywords and as a sentence), `seed` (a program calling `query.keyword_search` and, when available, `semantic_search`), `expand` (a program: the neighbours and the paths between the seeds, as text with node ids), `answer` (the model, told to cite node ids), `verify` (a program: every cited id is in the subgraph; error exit `uncited`), and a fallback that says what the graph does not contain instead of answering from memory.
- The report states whether the answer is **grounded** (cites nodes, all found) or **ungrounded** (a model answer with no graph support), as `problem_solver` marks `UNVERIFIED`. Never present an ungrounded answer as grounded.
- CLI: `workgraph ask "..."` with a call cap by default (a small one); the UI gets an Ask tab later.
- Acceptance: the questions in `docs/GUIDE/TUTORIAL.md` ("what you can ask") answered with citations on `examples/acme-shop`, offline with a scripted model, and once with a real one (capped).

**Result of Phase 3:**

- `recipes/ask/` (graph, `prompts/{keywords,answer,repair}.md`, `tools/ask_tool.py` with modes `context`, `verify`, `report`) and `workgraph ask QUESTION [--graph] [--semantic] [--adapter] [--recipe] [--max-calls N]` (default cap 4; a full run is 3 calls: search words, answer, one repair). Exits 1 unless grounded.
- **Design change from the plan:** `seed` and `expand` are one program step (`context`), and there is no separate model-free `fallback` node: when nothing matches, the report is written by the program (`empty`) and **no model answer is given**, which is stricter than the plan's "say what the graph lacks". `uncited` is not an error exit: a failed second check ends in a report marked **UNGROUNDED** that shows the answer and says not to rely on it, so the user still sees it. The model never decides the status; the program does.
- `Recipe` now replaces a recipe's `python3` command with `sys.executable`, so a recipe's program can import workgraph (and the extract_items parser runs in the same Python).
- **Checked:** 8 scripted tests (grounded first time; repair; an invented id stays UNGROUNDED; no match = 1 call and no answer; the call cap; the command's output and exit code; a missing graph says to build first). Real haiku, 3-call cap, on `examples/`: "Which design decision and which test cover REQ-001?" -> ADR-001 and test_cart.py, grounded; "Who owns the shop product and which processes does it follow?" -> the Payments team, `process:delivery` and `process:sdlc`, grounded; both match the tutorial's section 6. 118 tests pass.
- **Not done:** the UI Ask tab (the plan said later); gap questions ("which requirements have no test?") are not answered from the gap rules, only from what the matched nodes and their edges show.

### Phase 4: GraphLang files as knowledge-graph artifacts (opt-in per domain pack, see section 8, question 4)

- A processor `graflang` in `processors.py` (`REGISTRY`) for `*.graph.yaml` (and `*.bind.yaml`, `graflang.errors.yaml`): nodes for the workflow, each composite (part), prompt, procedure and policy; edges `uses`, `contains`, `reads_prompt`; stage tags from the domain's classifiers.
- Start with plain YAML parsing (no GraphLang import), so work-graph does not need GraphLang just to index its files. Optionally call GraphLang's loader for the exact flattened facts (cost, capabilities, error codes) when it is installed.
- Gap rules in the domain pack: a recipe with no test, a prompt no node uses, a part no graph uses, an error code the catalogue does not define.
- Dogfood: build a workspace over the `graflang` repo and read the result before adding more.

### Phase 5: embeddings through dd-embed (decided: do it now)

- Replace the ollama/sbert/TF-IDF code in `query.py` with dd-embed, keeping the `auto` fallback order and the cache in `<home>/cache/embeddings`. Check first that dd-embed has the same fallback and cache behaviour (verify); if it lacks something, add it to dd-embed. This phase does not depend on 2 to 4: it can run any time after Phase 0, and it is the better one to do second, because it also needs only a shared library and has a clear test (the same rankings on `examples/`).

## 4. What does not change

The CLI surface and file formats **except the renames of Phase 0b and the optional prompt and recipe names of Phase 2** (`graph.json`, the graph files, `workspace.yaml`, the area packs' schema), the home folder layout, the hooks and the plugin, sync, the UI, the shipped examples. A user who never uses `--semantic` or `ask` sees the renames only (and `utils migrate` handles an old home).

## 5. Dependencies and packaging

- GraphLang is on PyPI as `graflang` (the Python package is `graphlang`, version 0.2.1); it depends on `dd-llm[openai]`, `zinet` and others. work-graph already depends on `zinet`.
- Phase 1 needs only `dd-llm`. Phases 2 and 3 need GraphLang's runtime. **Decided: a core dependency** (the recipes are shipped features, and two code paths for one feature are more to keep right than one dependency). The old Python path for `llm_items` stays behind an environment switch only until the output matches (Phase 2), then goes.
- GraphLang's `kernel`, `spl`, `anthropic` and `gemini` extras are not needed: the recipes here use only `GENERATE` and `SOLVE` with a `subprocess` or `expression` backend.
- work-graph 0.2.0 is on PyPI, so a release with these changes is 0.3.0 with a changelog entry about the new dependencies.

## 6. Words (decided, `area` to confirm)

| Today | Becomes | What it is |
|---|---|---|
| layer (org, product, process, repo graph) | **domain** | one graph of one kind, with its own vocabulary and owner |
| domain, domain pack (`sdlc`, `research`, `publishing`) | **area**, area pack | the vocabulary (stages, flow relations, gap rules) and the processing of a project's artifacts |
| "layered graph" | the graph of domains | the whole, merged graph |

In GraphLang a *layer* is a level of composites inside one workflow (a short top graph, parts in subfolders); that word stays GraphLang's. Where work-graph's text
talks about GraphLang, it says "composite" or "part".

**Why `area` and not `space`:** work-graph already has a *workspace* (`workspace.yaml`), so "space" would read as part of that word; "space" also collides with "embedding space"
in the semantic search. "Area" is unused in the code (only as a table heading in the docs) and fits "a field of activity" (software, research, publishing). Frozen identifiers such as the
stage ids stay as they are.

## 7. Risks and what is not known

- **Not verified:** dd-llm `claude_cli` parity with `cc_cli.py` (model and timeout settings, `--tools ""`, launch retries); how the GraphLang runtime is called as a library with its run folders switched off; the start-up cost per document.
- **Behaviour drift in extraction.** Moving the prompt into a file and the parse into a tool must not change what `acme-shop` and `rq-demo` produce. The stub-model comparison in Phase 1 and 2 is the guard.
- **Cost.** Phase 3 adds a model call per question (analyse, answer, possibly a repair); cap every real run (`limits.max_llm_calls`) and keep the cap in the CLI default.
- **Scope.** Phases 2 and 3 are the value; Phase 4 is a bonus that makes work-graph describe its sibling projects; Phase 5 is housekeeping. Stop after any phase and the repo is in a consistent state.

## 8. Decisions

1. GraphLang as a core dependency (recommended) or an extra?

[WEN] yes

**Recorded:** core dependency, together with `dd-llm`, from Phase 0.

2. `ask` as a recipe in Phase 3 (recommended), or Python first and a recipe later?

[WEN] go with your recommend

**Recorded:** a recipe from the start (Phase 3).

3. Should a domain pack be able to name its own extraction prompt file (Phase 2), or is the shipped prompt, with the pack's vocabulary filled in, enough?

[WEN] we should support customization/extension

**Recorded:** yes, and more than the prompt: a pack's processor can name a prompt file or a whole recipe, and the user's `custom/` folder can hold them (Phase 2). My reading of
"customization/extension"; tell me if you meant only the prompt.

4. Phase 4: index GraphLang files in every workspace, or only when a pack (`sdlc`) lists the processor?

[WEN] not clear to me

**What the question is.** Phase 4 adds a processor that reads GraphLang files (`*.graph.yaml` and the files beside them) and turns recipes, parts, prompts and policies into
nodes of the knowledge graph. work-graph decides what to process per *domain pack*: the `sdlc` pack says "`*.py` goes to the code processor, `*.md` to the document
processor, prose to the LLM processor". Two ways to switch the new processor on:

- **Pack-listed (opt-in):** `sdlc.yaml` gets one more line, a processor with `match: "**/*.graph.yaml"`. Only projects whose pack lists it get recipe nodes. A project in the
  `research` or `publishing` pack ignores `.graph.yaml` files, as today. A user can add the line to their own pack in `custom/domains/`.
- **Built in (every workspace):** the processor always runs on every project, whatever its pack. Simpler to explain, but a research or publishing project that happens to contain a
  `.graph.yaml` file gets recipe nodes it has no stage vocabulary for (they would need tags from a pack that does not know recipes).

A project with no `.graph.yaml` files is unaffected either way. **Recommended: pack-listed**, because it is how every other processor works and keeps the stage tags meaningful.
I will plan on that unless you say otherwise.

5. Phase 5 now or never?

[WEN] now

**Recorded:** now. It is no longer optional, and it can run second, right after Phase 1 (section 3).

6. (new) The word "domain" is already taken inside work-graph by the domain pack (`sdlc`, `research`, `publishing`). Options:
   - (a) Use **domain** for the org, product, process and repo graphs in text and keep **domain pack** for the YAML packs (the plan's working choice; the two read differently in context but sit close).
   - (b) Use **graph pack** for the org, product, process and repo graphs and keep **domain** for the vocabularies (no collision; "pack" then means two things).
   - Either way, is it wording only, or are the identifiers renamed too (`layers.py`, `LAYER_KINDS`, the node field `layer`, `<out>/layers/`, `custom/graphs/`, `test_layers.py`, `test_layer_graph.py`)? A rename of the node field and the output folder changes `graph.json`, so it needs a migration for existing homes. I recommend wording only for now.

[WEN] refactor codes to replace "layers" with "domains", work-graph is in its early dev stage, let us do the right thing now. How about using "space" or "area" to designate `sdlc`, `research`, `publishing`

**Recorded:** the code is renamed, not only the words (Phase 0b, section 6): `layer` -> `domain`, and the old `domain` (the pack of `sdlc`, `research`, `publishing`) -> **`area`**. I recommend `area` over `space` (section 6: `workspace`, "embedding space"). Confirm `area`, or name another word, before Phase 0b starts. The renames are done in the order domain -> area first, then layer -> domain, with a one-release compatibility read of the old keys and a `utils migrate` command (Phase 0b).

7. (new) After the rename the word "layer" is left in work-graph for one thing only: the **process layer** (stage and project hub nodes) and the **knowledge nodes** (artifacts) of the built graph (`pipeline.knowledge_nodes()`, the README's "Graph model"). GraphLang's "layer" is a different thing again. Keep it as it is, or rename these two (for example "process nodes" and "knowledge nodes", `knowledge_nodes()`)? I recommend renaming them too, but it touches only one function and the docs, so it can wait.
