# work-graph code review (Opus 5.5)

Date: 2026-11-25 · Commit reviewed: `5eb4599` (main) · Scope: `src/workgraph/` (about 5,000 lines), the `ask` recipe, the tests.

The working tree had your uncommitted `docs/GUIDE` renames (SETUP.md → Setup.md and so on). I reviewed it as it is and changed
nothing in it except adding this file.

**How I checked it.**

- I read the Claude Code hooks (`claude_code.py`), the sync code (`syncing.py`: the guard, archive extraction, the private-repo
  check), and the `ask` recipe's verifier (`recipes/ask/tools/ask_tool.py`).
- `pytest`: **122 passed, 3 failed** (14.8 s). See B3.
- Every bug marked **confirmed** was reproduced by calling the code directly.

## 1. Summary

work-graph is a thoughtful layer over graphify:

- area packs keep the vocabulary in YAML;
- the LLM seam is one module (`llm.py`, every backend a dd-llm adapter);
- the hooks are written never to raise;
- the sync tree is guarded against databases, large files and secrets, and refuses a public repository.

The weak point is **`ask`'s grounding check**. It labels an answer `grounded` when at least one cited id is real, so an answer with
an invented claim passes (B1). And it counts any bracketed text as a citation, so ordinary Markdown fails (B2). Then, the test suite
is red on the installed graphify, because the pin has no upper bound (B3).

## 2. Strengths

| Area | What is good |
|---|---|
| One LLM seam | `llm.py` is the only code that calls a model; backend resolution order is explicit and documented; `claude_cli` never bills the API (dd-llm strips the keys). A `BackendLimitError` stops the LLM pass with a warning instead of failing the build. |
| Area packs | Vocabulary and processing in YAML; `utils validate-pack` lists every problem; a workspace can mix areas per project. |
| Status decided by a program | `ask` reports `grounded` / `ungrounded` / `empty` from `verify`, never from the model; an empty context gives no model answer at all (`ask_tool.py:75-83`). |
| Hooks stay out of the way | `handle()` swallows every error (`claude_code.py:175-182`); the rebuild is detached (`start_new_session=True`); `claude-setup` backs up `settings.json` before merging, and never duplicates an entry. |
| Sync safety | `guard_tree` stops databases (by suffix *and* by the SQLite header), files over 5 MB and six secret patterns; `_safe_extract` refuses links, devices, absolute and `..` paths, and checks every resolved target; `check_private` asks `gh` and refuses a public repo (`syncing.py:87-336`). |
| Home folder | Everything under `$WORKGRAPH_HOME`; graphify's caches redirected there, so nothing is written into projects; tests redirect the home through an autouse fixture. |

## 3. Bugs

### B1 (Medium, confirmed): one real citation makes a whole answer "grounded"

`verify` (`ask_tool.py:63-72`) checks only that every cited id is in the facts, and that at least one is cited. It does not check
that each claim carries a citation:

```
verify("Login is required [req:login]. The service also stores passwords in plain text and was written in 1987.",
       {"ids": ["req:login", "code:auth.py"]})
-> {'ok': True, 'cited': ['req:login']}          # reported as "grounded"
```

`grounded` is the word the user trusts. Here it covers two sentences that nothing in the graph supports.

**Fix:** split the answer into sentences (or bullet lines), and require a citation in each one that makes a claim. Report the
uncited ones as the repair message, which the recipe's one repair round can act on. Then the status means "every claim cites the
graph". That is still not "every claim is true", and the report could say so in one line.

### B2 (Medium, confirmed): any bracketed text counts as a citation

`CITE = r"\[([^\[\]\n]{2,200})\]"` (`ask_tool.py:18`) matches Markdown link text, footnote marks and asides:

```
verify("See the docs (link [here]) and [req:login].", ctx)
-> {'ok': False, 'error': 'it cites ids that are not in the graph facts: here'}
```

Models write `[text](url)`, `[1]` and `[sic]` freely, so a correct answer is marked `ungrounded`, or spends its repair round on
formatting.

**Fix:** match only id-shaped citations. Node ids have a known form (`<kind>:<path>`, or the ids in `ctx["ids"]`), so match those
exactly, or require a prefix such as `[id:…]`. Skip `[...]` that is followed by `(`.

### B3 (Medium, confirmed): the tests fail on the installed graphify; the pin has no upper bound

`pyproject.toml:27` has `graphifyy[sql]>=0.7.19`; the `graf` environment has **0.9.92**. Three tests now fail:

```
test_home_and_claude.py::test_build_uses_default_workspace_and_writes_to_home     '31 nodes' expected, the build gives 26
test_home_and_claude.py::test_relative_config_falls_back_to_the_home_workspace    (same)
test_ui.py::test_app_overview_keyword_and_semantic_search                          '70' expected, got '60'
```

The code paths are unchanged (the tests date from 2026-11-22). The structural build of `examples/acme-shop` simply yields fewer nodes,
which points to graphify's AST extraction. I did not install an older graphify to prove it, so that cause is likely, not confirmed.
Either way, a graph's size changes silently under a dependency upgrade, and the gap rules run on that graph.

**Fix:**
- pin a range that is known to work (`graphifyy[sql]>=0.7.19,<0.10`) and record the tested version;
- make the tests assert on the nodes that matter (the acme-shop gaps, named nodes) rather than on totals.

## 4. Weaknesses and smaller notes

- **The SessionStart hook tracks every folder a session opens.** It adds it to the default workspace and starts a build
  (`claude_code.py:145-156`), with only the home folder excluded. A session opened in `~/Downloads` or in a scratch clone joins the
  graph. A tracked project's labels (file front matter, LLM work items) are then printed into **every later session's context**
  (`context_summary`). For a cloned third-party repo, that is untrusted text in the model's context. An opt-in (`workgraph track`),
  or an allow-list of parent folders, would keep it to your projects.
- **The build lock trusts a PID** (`build_running`, `claude_code.py:61-67`). After a build ends, its lock remains. If the PID is
  reused by another process, every later rebuild is skipped until that process exits. Writing the start time next to the PID, or
  using `fcntl.flock` on the lock file, fixes it.
- **Hook commands are not quoted** (`hook_settings`: `f"{exe} hook {name}"`). A `workgraph` installed under a path with a space
  gives a broken hook; `shlex.quote(exe)` fixes it.
- **`session_end` parses `git status --porcelain` by splitting on spaces.** A rename gives `a -> b`, and a path with spaces arrives
  quoted. `--porcelain=v1 -z` parses exactly.

## 5. Gaps

- **No test where an answer mixes a cited claim with an uncited one** (B1), or contains Markdown links (B2).
- **README's "planned" markers lag the code**, as CLAUDE.md admits. `ask` and `viz` exist.
- **The UI tests need a working numpy/pyarrow** and are run in the same `graf` environment here. One of them failed for B3's reason,
  not for the environment.

## 6. Suggested order

1. **B3:** pin graphify, and make the counts robust (a red suite hides new failures).
2. **B1** and **B2** together: both are the verifier, and both change what `grounded` means.
3. The hook's tracking scope, then the lock.
