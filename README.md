# workgraph

**A personal AI assistant powered by a knowledge-base graph, for the whole software development lifecycle, and for the knowledge around it.**

Inspired by [graaph.org](https://graaph.org/), but aimed past the coding assistant. Code is one kind of knowledge among many. `workgraph` treats everything you produce and consume while building software as nodes in one graph. That includes requirements, design decisions, code, tests, bugs, meetings, papers, and half-formed ideas. The assistant reasons over that graph instead of over a single file or chat window.

> Status: hackathon project, early prototype.

---

## Why

Most AI coding assistants see a snapshot: the open file, a few neighbors, a chat history. The things that make software work sit outside that window:

- *Why* was this designed this way? (a decision made three months ago)
- Which requirement does this function satisfy, and which tests cover it?
- Which paper, ticket, or Slack thread explains this odd workaround?
- What did I learn last time I hit this class of bug?

That knowledge is scattered across repos, docs, tickets, notes, machines, and your head. It is **relational**, so a graph is a natural way to store it. `workgraph` makes the graph the assistant's long-term memory and its source of grounding.

## Vision

1. **One graph, many artifact types.** Code, docs, tickets, decisions, notes, and external references live together and are linked.
2. **Lifecycle-aware.** The graph models the product lifecycle (idea → spec → design → build → test → release → operate), so traceability comes for free.
3. **Personal first.** It runs locally, is owned by you, and is plain-file persistent. It is a second brain for how you build.
4. **Graph-grounded answers.** The LLM retrieves a *subgraph* (a node plus its neighborhood and the paths between nodes) as context, not just top-k text chunks. Answers can cite the nodes they used.
5. **Beyond coding.** The same engine handles knowledge management: reading notes, research, meeting outcomes, and personal retrospectives.
6. **Many graphs, one runtime.** The repo graph is the first of several domain graphs (below). They reference each other instead of copying nodes.
7. **Two formats, one model.** JSON is the canonical machine format, and YAML is the human format for review and audit.
8. **Graph artifacts drive AI workflow.** The graph files are the working memory of the AI-assisted process, not a report generated at the end (below).

### Graph artifacts drive the AI workflow

Chat history and context windows are temporary, and each new session starts cold. The graph is **persistent context**: a file that outlives any one conversation and is shared by every tool that reads it.

- **Persistent context for LLMs and coding agents.** Before a task, an agent loads the relevant sub-graph (the requirement, its design decision, the code that implements it, the tests that verify it, the team that owns it) instead of re-discovering them from raw files. Every session starts from the same grounded state.
- **The graph steers the work.** Gap rules ("spec has no test"), process stages and open work items tell the agent what to do next. The agent's output (a new design note, a test, an updated status) is written back into the graph, so the next step starts from it.
- **Human in the loop.** LLM-proposed nodes and edges are marked `INFERRED` until a person confirms them in the YAML review format. Agents and people read and write the same artifacts.
- **Tool-neutral.** Any LLM or coding agent can use the same files, whether it is Claude Code, another assistant or a script. Nothing depends on one tool's private memory.

This is the same graph-first approach as ConceptBook (a book as a graph) and Graph-Code (a blueprint as a graph), applied to the software development process itself. The wider vision is in `README-graph-vision.md` in the ZiNets repository.

### Search and review

`workgraph search "checkout test"` is a keyword search (names, paths, summaries and the first lines of each file, with phrase and prefix matching).

`workgraph ask "Which design decision and which test cover REQ-001?"` answers a question in words. A model picks search words, a program collects the matching nodes and their neighbours, the model answers and must cite node ids in square brackets, and a program checks that every cited id is one of the facts it was given. The report says **grounded** (cites real nodes, listed) or **ungrounded** (the answer is shown, marked, and not to be relied on), and when nothing in the graph matches there is no model answer at all. It is the GraphLang recipe `src/workgraph/recipes/ask/`, costs at most 3 model calls (`--max-calls` caps it, default 4), and exits non-zero unless the answer is grounded. `workgraph search "how are carts stored?" --semantic` ranks by meaning with embeddings from a local Ollama model (default `nomic-embed-text`) or sentence-transformers, and says plainly when it had to fall back to lexical TF-IDF. `workgraph show REQ-002` prints one node and its links. `workgraph ui` opens a Streamlit app to browse, filter, search, inspect gaps, see a node's neighbourhood and draw the graph (Map tab). `workgraph viz` draws the graph (`--engine cytoscape|graphviz|mermaid|ascii|pyvis|graphify`; the default `cytoscape` page is interactive and works offline; `--node ID --hops N` draws one neighbourhood).

### Memory for Claude Code

Two Claude Code hooks (installed by the `workgraph` plugin or `workgraph utils claude-setup`) make the graph the memory of your sessions. When a session starts, the project is tracked automatically and a short summary of what the graph knows about it (stages, gaps, open items, product, owner, what earlier sessions changed) is added to the session context. When the session ends, what changed is recorded and the graph is rebuilt in the background. Work done through Claude Code then flows into the same graph as everything else, with no manual ingestion. The `/workgraph` slash command queries the graph from inside a session. Data lives in `~/workgraph` (override with `WORKGRAPH_HOME`), and any local folder or git URL can be ingested with `--src`. `workgraph import-claude` backfills the work Claude Code has already done (the projects it worked in, session metadata, and its memory files as searchable nodes).

### Several machines

The database never leaves the machine. What cannot be rebuilt (domain files, YAML comments, the portable workspace) travels as text: `workgraph dump` / `load` for a first setup by USB, then `workgraph sync push` / `pull` through a **private** GitHub repository. Exports and pushes are scanned and stop on databases, large files or anything shaped like a key; the org domain, session journal and LLM cache are opt-in. See the User Guide, "Moving to another machine".

`workgraph utils claude-setup --write` installs the hooks and the `/workgraph` command into your user-level Claude Code settings. The same pieces also exist as a Claude Code plugin in `plugin/`, which is **not published to a marketplace yet** while it is being tested; to try it from a clone, run `claude --plugin-dir <path>/plugin`. Use one route or the other, not both.

### Multiple graphs

Today's graph covers repositories. The vision is a set of graphs, each with its own vocabulary (an area pack) and its own owner, that reference one another:

| Graph | Describes | Example hierarchy |
|---|---|---|
| **Repo** | code, docs, tests, decisions inside repositories (built today) | workspace > project > file > symbol |
| **Product** | what is shipped and how it is organized | product family > product > application |
| **Org** | who builds and owns it | company > division > department > group > team > person |
| **Process** | how work is delivered, as a reusable template | stakeholder interview > requirement spec > solution design > prototyping > build > test > release > feedback |

- **The product lifecycle is one process among many.** The `develop`, `research` and `publish` packs are already small process graphs. A process graph generalizes them, and a new delivery process is a new pack.
- **Template versus instance.** A process graph defines the template ("design follows requirements"). A product's progress through it is an instance with status, owners and artifacts. The two are kept apart so that "what the process says" is never confused with "where we are".
- **Hierarchies are containment.** Each level is joined to its parent by `part_of`. A **sub-graph** is a node plus its descendants, so a team, a product or a single process stage can be addressed, queried and exported on its own.
- **Graphs reference each other.** A repo says `belongs_to: product:checkout`. A product says `owned_by: org:acme/payments`. A product says `follows: process:develop`. Org and process nodes are defined once and referenced everywhere, so the same team or stage never exists as several copies.

### Graph references

References exist for brevity in the spec. At run time they are always resolved in memory:

1. **Spec time.** A graph file refers to a node or a whole sub-graph in another graph by a namespaced ID (`org:acme/payments`, `process:develop`) instead of repeating it.
2. **Load time.** The loader resolves every reference and expands sub-graph references, merging all domains into **one in-memory graph**. Each node keeps a `domain` attribute, so queries, clustering and gap analysis work across domains without special cases.
3. **Integrity.** An unresolvable reference (renamed, moved or deleted target) is reported as a broken reference, like the broken-reference check that already exists for requirements. Stable IDs matter here, because path-style IDs break when a team is reorganized.

### Dual formats: JSON and YAML

Each graph is stored in two interchangeable formats:

| Format | For | Used for |
|---|---|---|
| **JSON** | machines | the canonical form: internal schema validation, referential integrity checks, tooling, and the `graph.json` already written by `build` |
| **YAML** | people | review and audit: more readable, and reviewers can add comments and annotations |

Converters go both ways (JSON <-> YAML). The conversion must be lossless for graph content. Validation always runs on the JSON form, and the human edits made in YAML flow back through the same validation.

**Comment store.** YAML comments have no JSON equivalent, so a plain YAML-to-JSON conversion would lose them. A small database (SQLite) tracks every graph file and keeps its comments:

- **Registry.** One row per `.json`/`.yaml` graph file, with its path, domain and content hash, so the tool knows which pairs belong together and when one side has changed.
- **Comments.** When YAML is converted to JSON, each comment is saved with an anchor (file, node ID, key path, and whether it is a leading, trailing or block comment) instead of a line number, so it survives reordering and reformatting.
- **Restore.** When JSON is converted back to YAML, the saved comments are re-attached by anchor, so the original comments return even though the JSON never held them.
- **Orphans.** If the node a comment was anchored to has been deleted or renamed, the comment is kept and reported as orphaned instead of being silently dropped.

## Core ideas

### Built on graphify, adapted per area

The engine is [graphify](https://github.com/Graphify-Labs/graphify), used as a library from PyPI. It supplies file detection, tree-sitter extraction for about 25 languages, LLM semantic extraction with pluggable backends, entity dedup, Leiden clustering, graph queries and export. The graph is a NetworkX graph throughout.

`workgraph` is a thin layer that adapts it to an **area** by supplying an *area pack*, a YAML file with two halves:

| Domain | What the pack defines | Example (`develop`) |
|---|---|---|
| **Vocabulary** | stages (a constrained tag set) and their flow, legal relations, gap rules, path classifiers | idea → spec → design → build → test → release → operate; `test --verifies--> spec` |
| **Processing** | which artifact types go through which processor and LLM backend | `*.py` → tree-sitter; `*.md` → frontmatter; `*.pdf` → LLM (`claude-cli`) |

Shipped packs (`src/workgraph/areas/`): **`develop`** (the product lifecycle idea → spec → design → build → test → release → operate, for software, hardware or both; it replaces the former `sdlc` and `design` packs, whose names still load it), **`research`** (question → literature → hypothesis → experiment → analysis → write-up, where code is an experiment) and **`publish`** (idea → outline → draft → edit → publish → promote). A new area is a new YAML file. A workspace can mix areas, since each project picks its own pack, and all of them land in one graph.

### Graph model

- **Process nodes**: `stage:<area>:<id>` nodes joined by `precedes`, and `project:<name>` nodes joined to the stages they take part in.
- **Knowledge nodes**: artifacts (files, symbols, documents, and typed nodes such as requirements, decisions, questions and hypotheses) with a `kind`, a `project`, and `stages`, a **list of stage tags** validated against the pack's vocabulary. A node may carry several tags, such as `[requirement, design]`. Each tag is also an `in_stage` edge.
- Edges carry `relation` and `confidence`: `EXTRACTED` (explicit in source), `INFERRED` (derived or LLM-suggested), or `AMBIGUOUS`.
- Analysis and clustering run on the knowledge nodes only, because stage and project nodes are hubs that would skew them.

### Explicit links, derived links, gaps

- **Frontmatter**: `satisfies: [REQ-001]` in a markdown file creates an edge. Relation names come from the pack's `flow_relations`.
- **Annotations**: `# verifies: REQ-001` in any code file does the same.
- **Derived**: a test file that imports a code file yields an `INFERRED` `verifies` edge, and the rule comes from the pack's `flow_relations` rather than from code.
- **Gaps**: the pack's `expectations` ("every requirement needs a test") are evaluated as plain graph queries. Rules can skip trivial files (`min_symbols`, `exclude`), and broken references are reported too.
- **GraphLang files** (the `graflang` processor, listed by the `develop` and `research` packs; a pack that does not list it ignores them): `*.graph.yaml`, `*.bind.yaml` and `graflang.errors.yaml` are read as plain YAML (GraphLang itself is not run). A workflow becomes a `recipe` node, or a `part` node when it sits in a subfolder of a folder that holds a graph itself; `bindings`, `error_code`, `policy` and `procedure` nodes follow. Edges: `uses` (recipe to part), `reads_prompt` (to the prompt's own document), `runs` (to the program in a `command:`), `may_add` (a MUTATE catalogue), `governed_by`, `runs_procedure`, `raises` (to the error code's definition), `binds`, and an `INFERRED` `verifies` from a test that names the recipe (its path, its name or its folder in quotes; parts get none). The `sdlc` pack's gap rules: "recipe has no test" and "part is used by no recipe"; build warnings: a prompt declared but unused, a prompt file no graph names, a named file that does not exist, an error code nobody defines. Files in folders the project ignores (`build/`, `logs/`) are skipped quietly.
- **LLM work items** (`--semantic`): the `llm_items` processor reads planning and design prose (roadmaps, todos, design notes) with the pack's own prompt and extracts requirements, decisions and tasks as `INFERRED` nodes (`origin: llm`, with `status: done|open`) tagged with the pack's stages. They link to their source document with `derived_from`, are cached by prompt hash, and don't trigger gap rules until confirmed. The extraction is a [GraphLang](https://github.com/digital-duck/graflang) recipe, `src/workgraph/recipes/extract_items/` (a prompt, plus a small program that takes the JSON out of the reply and keeps only the pack's kinds and stages). To change it, give the processor `prompt: items.md` (a file in `<home>/custom/prompts/`, or a path; the prompt uses `{{in_area}}`, `{{in_kinds}}`, `{{in_stages}}`, `{{in_flow}}`, `{{in_max_items}}`, `{{in_path}}`, `{{in_text}}`) or `recipe: my_items` (a folder in `<home>/custom/recipes/`; it must take the inputs `area, kinds, stages, flow, max_items, path, text` and give the output `items`, JSON text `{"items": [...]}`). `workgraph utils validate-pack` checks both names.
- **Cross-project links**: byte-identical files get `identical_to` and same-path files that differ get `variant_of`, so clones of a template across repos show up (`workgraph utils clones`).
- **Ignore rules**: `.gitignore`, `.graphifyignore`, the pack's default `ignore:` (logs, locks, db files) and a per-project `ignore:` list in the workspace file.

### Retrieval: graph + semantic

Seed nodes by keyword and (with `--semantic`) embedding, expand to their neighbours and the edges among them, then pass that subgraph to the LLM with node IDs so answers can cite them. `workgraph ask` does this today; a program, not the model, checks every citation. Ranking and pruning larger subgraphs is still to come.

## What you can ask

- *"Why does `login()` use OIDC?"* → follows `implements` → `satisfies` → `decided_by` to the ADR.
- *"What breaks if I change `User.email`?"* → impact analysis over `depends_on`, `calls`, and `tests`.
- *"Which requirements have no tests?"* → graph query for coverage gaps.
- *"Summarize what I learned about rate limiting this month."* → knowledge management across notes and sources.
- *"Draft a design doc for X using what I already know."* → generation grounded in the subgraph.
- *"Show me orphaned decisions and stale docs."* → graph health checks.

## Architecture

```
 sources ──▶┌──────────────┐
 (per domain)│  Ingestors   │  code · git · markdown · notes · web
            └──────┬───────┘
                   ▼
   domain files (one per domain: repo · product · org · process)
   ┌─────────────┐   convert    ┌─────────────┐
   │ JSON        │◀────────────▶│ YAML        │  human review and audit,
   │ canonical   │  (lossless)  │ with        │  comments added here
   │ + validation│              │ comments    │
   └──────┬──────┘              └──────┬──────┘
          │          ┌─────────────────┴──┐
          │          │ SQLite             │  file registry + comment store,
          │          │                    │  restores comments on JSON -> YAML
          │          └────────────────────┘
          ▼
   ┌──────────────┐
   │ Loader       │  resolves graph and sub-graph references, checks
   │              │  referential integrity, merges domains
   └──────┬───────┘
          ▼
            ┌──────────────┐
            │ Knowledge    │  one in-memory graph, every node tagged
            │ Graph        │  with its domain
            │ (NetworkX)   │
            └──────┬───────┘
                   ▼
            ┌──────────────┐      ┌────────────┐
            │  Retriever   │◀────▶│ Embeddings │  local or API
            └──────┬───────┘      └────────────┘
                   ▼
            ┌──────────────┐
            │  Assistant   │  LLM + tools (query, link, summarize, generate)
            └──────┬───────┘
                   ▼
              CLI · Web UI · graph visualization
```

## Tech stack

Python 3.10+ (conda env), NetworkX, graphify (PyPI `graphifyy`), ruamel.yaml / PyYAML, Streamlit. Sibling libraries: [dd-llm](https://pypi.org/project/dd-llm/) (every LLM call: Claude Code subscription, Anthropic API, Bedrock, Gemini, OpenAI, Ollama, ...), [dd-embed](https://pypi.org/project/dd-embed/) (embeddings: Ollama, sentence-transformers), [GraphLang](https://github.com/digital-duck/graflang) (`graflang`, runs the recipes in `src/workgraph/recipes/`) and [zinet](https://pypi.org/project/zinet/) (drawing engines and comment-preserving YAML).

## Documentation

- `README-graph-vision.md` in the ZiNets repository: the graph-first vision across the ZiNets ecosystem (ConceptBook, Graph-Code, and this project) and why a declarative graph is the common intermediate representation
- [docs/GUIDE/SETUP.md](https://github.com/digital-duck/work-graph/blob/main/docs/GUIDE/SETUP.md): installation, `cc_cli` (subscription) and Bedrock setup, troubleshooting
- [docs/GUIDE/USER-GUIDE.md](https://github.com/digital-duck/work-graph/blob/main/docs/GUIDE/USER-GUIDE.md): getting started, workspace files, linking conventions, commands, customizing area packs

## Quickstart

```bash
conda create -n graf python=3.11 pip -y && conda activate graf   # dedicated env, see docs/GUIDE/SETUP.md
python -m pip install -e ".[dev]"
workgraph utils doctor                                      # confirm you are in graf, not conda base

workgraph utils areas                                     # list area packs
workgraph build -c examples/workspace.yaml            # build the graph, write ~/workgraph/out/graph.json
workgraph gaps --src https://github.com/digital-duck/work-graph   # any local folder or git URL, no workspace file
workgraph gaps  -c examples/workspace.yaml            # report gaps per area rules
workgraph utils clones -c examples/workspace.yaml           # files shared across projects
workgraph utils check -c examples/workspace.yaml            # validate the org/product domain files and cross-graph references
workgraph utils convert examples/graphs/product.json        # JSON <-> YAML, YAML comments kept in the store
workgraph open --semantic --adapter cc_cli -c examples/acme-shop/workspace.yaml   # open work items via the LLM pass
workgraph search "checkout test"                     # query the last build; also: show NODE, status, ui, viz
workgraph ask "Which test covers REQ-001?"            # grounded answer citing node ids (a few model calls)
python -m pytest
```

`examples/` holds a small software project (`acme-shop`), a hardware-and-software product (`plant-waterer`) and a research project (`rq-demo`) with deliberate gaps, plus a workspace that builds both into one graph. LLM processors are off unless you pass `--semantic`.

Upgrading a home folder from 0.2.x (`domain:` became `area:`, `layer:` became `domain:`): run `workgraph utils migrate` once (`--dry-run` to preview), then `workgraph build` again. See CHANGELOG.md.

## LLM backends (home vs work)

All LLM calls go through one seam, `src/workgraph/llm.py`, which asks a [dd-llm](https://github.com/digital-duck/dd-llm) adapter. The backend is chosen in this order: explicit argument, then the `WORKGRAPH_BACKEND` environment variable, then the project's `backend:` in `workspace.yaml`, then the processor's `backend:` in the area pack, then the default `cc_cli`.

| Backend | Billing | Notes |
|---|---|---|
| `cc_cli` (default) | **Claude Code subscription** | dd-llm's `claude_cli` adapter (shared with GraphLang and SPL.py). Strips `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY` and the nested-session guards from the environment, so `claude` always uses your stored login. Prompt via stdin, tools off, launch retries, distinct rate-limit error. |
| `claude-cli` | **Claude Code subscription** | graphify's old name for the same CLI; it now means `cc_cli` (the adapter strips the billing variables). |
| `claude` | API, per token | dd-llm `anthropic`; needs `ANTHROPIC_API_KEY` |
| `bedrock` | your AWS account | dd-llm `bedrock` |
| `gemini`, `openai`, `ollama`, `deepseek`, ... | API per token, or local (`ollama`) | any dd-llm adapter name works (`python -c "import dd_llm; print(dd_llm.list_adapters())"`) |

```bash
# home: subscription, nothing to set
workgraph build --semantic -c workspace.yaml

# work: AWS Bedrock, same workspace file, no YAML edits
python -m pip install -e ".[bedrock]"
export WORKGRAPH_BACKEND=bedrock AWS_PROFILE=<profile> AWS_REGION=<region>
export WORKGRAPH_MODEL=<model-or-inference-profile-id>
workgraph utils show-llm -c workspace.yaml          # resolved backend, billing mode and readiness checks per processor
workgraph build --semantic -c workspace.yaml
```

Model and timeout: `WORKGRAPH_MODEL` (any backend; `WORKGRAPH_CC_MODEL` for `cc_cli` and `GRAPHIFY_BEDROCK_MODEL` for `bedrock` still work; empty = the adapter's default) and `WORKGRAPH_CC_TIMEOUT` (default 1200 s). LLM results are cached by backend and prompt, so switching backends re-extracts once. A session or rate limit stops the LLM pass with a warning instead of failing the build; rerun later and the cached documents are skipped.

## Layout

```
src/workgraph/
  areas/*.yaml   # area packs: develop, research, publish
  area.py        # Area / Workspace loading, stage-tag validation, path classifiers
  llm.py           # the LLM seam: backend resolution, billing labels, one `complete()` over dd-llm adapters (cc_cli at home, bedrock at work)
  recipes/         # GraphLang recipes shipped with workgraph (extract_items, ask) and `Recipe`, which runs one through the LLM seam
  processors.py    # processing: ast, frontmatter, annotations, graflang, llm, llm_items
  links.py         # cross-project identical_to / variant_of edges
  pipeline.py      # tag + link + derive flow edges + cluster (wraps graphify)
  progress.py      # per-project / per-phase progress and timings for build
  analyze.py       # gap analysis from a pack's expectations
  viz.py           # workgraph's style and node selection for zinet's drawing engines
  migrate.py       # utils migrate: 0.2.x -> 0.3.0 words; graph.json format version
  cli.py
examples/          # acme-shop (develop), plant-waterer (develop, hardware and software), rq-demo (research), workspace.yaml (both)
```

Multi-graph modules (design in [docs/DEV/README-design.md](https://github.com/digital-duck/work-graph/blob/main/docs/DEV/README-design.md)):

```
src/workgraph/
  schema.py        # domains, kinds, relation rules, validation of domain files
  refs.py          # load domain files, expand /** sub-graph references, merge into the build graph
  domains.py       # the domain map (domains as nodes) and the per-domain partitions under <out>/domains/
  convert.py       # JSON <-> YAML converters; harvests and re-attaches YAML comments
  store.py         # SQLite: graph-file registry, comment store, uid history, Claude Code session journal
  paths.py         # the home folder (~/workgraph or $WORKGRAPH_HOME) and its layout
  sources.py       # --src <URL or path>: ad-hoc workspaces, shallow clones into <home>/src
  tracking.py      # init / track: the default workspace
  syncing.py       # export/import tar.gz, sync through a private git repo, privacy guards
  claude_import.py # Claude Code memory processor and import-claude
  claude_code.py   # Claude Code hooks: workgraph as the memory of your sessions
  query.py         # load, keyword search, semantic search (dd-embed adapters: ollama / sentence-transformers, else TF-IDF), neighbourhoods
  ui/streamlit/    # Streamlit app (`workgraph ui`); one folder per UI framework under ui/
  data/            # packaged copy of the /workgraph command
plugin/            # Claude Code plugin: hooks + the /workgraph command (not published; draft marketplace file in docs/DEV/)
examples/graphs/   # org and product domain files (JSON canonical, YAML for review)
```

## Hackathon scope

**Must have (MVP)**
- [x] Area packs (`develop`, `research`, `publish`) with constrained stage tags
- [x] Ingest code (tree-sitter) and Markdown with frontmatter; annotations; derived `verifies` edges
- [x] Gap analysis and broken-reference reporting
- [x] Persist the graph (`graph.json`) and load it back for search, `show`, `status` and the UI
- [x] `ask` command: seed → expand → LLM answer with cited nodes, citations checked by a program
- [x] `workgraph viz`: draw the graph with a choice of engines (see docs/DEV/README-vis.md)
- [x] Streamlit app to review and query the graph (`workgraph ui`): overview, keyword and semantic search, browse, gaps, a node's links and neighbourhood
- [ ] Interactive visualization of the whole graph
- [x] Graph references: namespaced IDs, resolved in memory at load time, with broken-reference reporting across graphs
- [x] Product domain (thin): a repo `belongs_to` a product, and a product `follows` a process template

**Should have**
- [x] Dual formats: JSON (canonical, schema and referential-integrity validation) and YAML (review and audit), with converters both ways
- [x] Comment store: SQLite registry of graph files that saves YAML comments by anchor and restores them on JSON -> YAML
- [x] Sub-graph addressing (a node plus its descendants) for querying and export
- [x] Process domain: reusable process templates (such as stakeholder interview through feedback), separate from per-product instances
- [ ] Git history ingestion (commits ↔ files ↔ issues)
- [ ] LLM-proposed edges with accept/reject review
- [ ] Traceability and coverage-gap reports (requirement → code → test)
- [ ] Impact analysis ("what depends on this?")

**Stretch**
- [x] Org domain (company > division > department > group > team > person), kept optional and separable because of privacy
- [ ] Watch mode: incrementally update the graph as files change
- [x] Index GraphLang workflow files (recipes, parts, prompts, error codes) with their own gap rules
- [x] Claude Code integration: hooks (session memory), the `/workgraph` command and a plugin
- [ ] MCP server so assistants can call search and show as tools
- [x] Ingest existing Claude Code memory and history (`import-claude`, memory nodes)
- [x] Sync a workgraph between machines through a private GitHub repository, with a tar.gz for first setup; the database is never shared
- [ ] Team or enterprise mode (a shared server)
- [ ] Graph health dashboard (orphans, stale docs, superseded decisions)

## Demo story

1. Point it at a small real repo plus a few ADRs and meeting notes.
2. Show the graph as it forms.
3. Ask a "why" question that spans code, a decision, and a note, which no single-file assistant could answer.
4. Change a function and show the impact analysis.
5. Show the coverage-gap report and an LLM-suggested missing link.

## Design principles

- **Provenance matters.** Every edge records whether it was extracted, inferred, or user-confirmed.
- **Human in the loop.** The LLM proposes links, and you decide which ones become trusted.
- **Local and portable.** The graph is a file you own. Diff it, version it, and back it up.
- **Cite or stay quiet.** Answers reference graph nodes, and gaps are admitted.

## Acknowledgments

- [graaph.org](https://graaph.org/) for the inspiration
- [NetworkX](https://networkx.org/)
- [graphify](https://github.com/Graphify-Labs/graphify), the engine under this project
- The ZiNets graph-first vision: `README-graph-vision.md` in the ZiNets repository

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](https://github.com/digital-duck/work-graph/blob/main/LICENSE).
