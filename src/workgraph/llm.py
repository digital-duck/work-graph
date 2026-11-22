"""LLM seam: the one place that decides which backend serves a prompt, and the only one that calls a model.

Every backend is a dd-llm adapter (`dd_llm.get_adapter`), shared with GraphLang and SPL.py. The names users know stay:

    cc_cli      -> claude_cli   Claude Code *subscription*; dd-llm strips ANTHROPIC_API_KEY & co. from the call's environment.
    claude-cli  -> claude_cli   (graphify's old name; it is subscription-safe now, which graphify's own was not)
    claude      -> anthropic    Anthropic API, per token (ANTHROPIC_API_KEY)
    azure       -> azure_openai
    bedrock, gemini, ollama, openai, deepseek, ...   the dd-llm adapter of that name; so is any other dd-llm name.

Typical setup: `cc_cli` at home, `bedrock` at work (AWS account).

Resolution order, first hit wins:
    1. explicit argument            complete(..., backend="bedrock")
    2. WORKGRAPH_BACKEND env var   export WORKGRAPH_BACKEND=bedrock      <- switch machines without editing YAML
    3. project `backend:` in workspace.yaml
    4. processor `backend:` in the area pack
    5. DEFAULT_BACKEND (cc_cli)

Model and time: `WORKGRAPH_MODEL` (any backend; `WORKGRAPH_CC_MODEL` for cc_cli, `GRAPHIFY_BEDROCK_MODEL` for bedrock still work) and
`WORKGRAPH_CC_TIMEOUT` (seconds, cc_cli). A session, rate or quota limit raises `BackendLimitError`: callers stop instead of hammering the backend.
"""
from __future__ import annotations

import os
import shutil

from dd_llm import get_adapter, list_adapters
from dd_llm.adapters.claude_cli import STRIP_VARS, stripped_vars_present, subscription_env  # noqa: F401  (re-exported for callers and tests)

DEFAULT_BACKEND = "cc_cli"
ALIASES = {"cc_cli": "claude_cli", "claude-cli": "claude_cli", "claude": "anthropic", "azure": "azure_openai"}
BILLING = {
    "cc_cli": "subscription (Claude Code login; API-key env vars stripped)",
    "claude-cli": "subscription (same as cc_cli)",
    "claude": "Anthropic API, per token",
    "bedrock": "AWS account",
}
ENV_BACKEND = "WORKGRAPH_BACKEND"


class BackendLimitError(RuntimeError):
    """Session / rate / quota limit reached: stop calling this backend for now."""


def adapter_name(backend: str) -> str:
    """The dd-llm adapter that serves a workgraph backend name."""
    return ALIASES.get(backend, backend)


def resolve_backend(*candidates: str | None) -> str:
    """Pick the backend: explicit candidates in priority order, with the env var outranking config-file values.

    Call as resolve_backend(explicit, project_backend, processor_backend)."""
    explicit, *configured = candidates
    chosen = explicit or os.environ.get(ENV_BACKEND) or next((c for c in configured if c), None) or DEFAULT_BACKEND
    if adapter_name(chosen) not in list_adapters():
        raise ValueError(f"unknown LLM backend {chosen!r}; available: {sorted(set(ALIASES) | set(list_adapters()))}")
    return chosen


def _model(backend: str) -> str:
    env = os.environ
    if backend in ("cc_cli", "claude-cli", "claude_cli"):
        return env.get("WORKGRAPH_MODEL") or env.get("WORKGRAPH_CC_MODEL") or ""        # "": dd-llm's default for the CLI
    if adapter_name(backend) == "bedrock":
        return env.get("WORKGRAPH_MODEL") or env.get("GRAPHIFY_BEDROCK_MODEL") or ""
    return env.get("WORKGRAPH_MODEL") or ""


def complete(prompt: str, *, backend: str, max_tokens: int = 4096, allowed_tools: list[str] | None = None) -> str:
    """Send a plain-text prompt to the backend and return the reply text. Raises BackendLimitError on a limit, RuntimeError on any other failure."""
    kwargs: dict = {}
    if adapter_name(backend) == "claude_cli":
        if os.environ.get("WORKGRAPH_CC_TIMEOUT"):
            kwargs["timeout"] = int(os.environ["WORKGRAPH_CC_TIMEOUT"])
        if allowed_tools:
            kwargs["allowed_tools"] = allowed_tools
    resp = get_adapter(adapter_name(backend), **kwargs).call(prompt, model=_model(backend), max_tokens=max_tokens)
    if resp.success:
        return resp.content
    err = (resp.error_history or [{}])[-1]
    msg = err.get("error") or "the backend returned no answer"
    if err.get("error_type") == "ModelOverloaded":
        raise BackendLimitError(msg)
    raise RuntimeError(msg)


def check_backend(backend: str) -> list[tuple[str, bool, str]]:
    """Local, offline readiness checks for a backend: [(check, ok, detail)]. Makes no network calls."""
    out: list[tuple[str, bool, str]] = []
    name = adapter_name(backend)
    if name == "claude_cli":
        path = shutil.which("claude")
        out.append(("`claude` on PATH", bool(path), path or "install Claude Code and run `claude` once to log in"))
        if path:
            ok, detail = _claude_login()
            out.append(("subscription login", ok, detail))
        set_vars = stripped_vars_present()
        out.append(("billing env vars stripped for the call", True,
                    ", ".join(set_vars) + " (set in this shell, removed for the call)" if set_vars else "none set"))
    elif name == "bedrock":
        try:
            import boto3  # noqa: F401
            out.append(("boto3 installed", True, ""))
        except ImportError:
            out.append(("boto3 installed", False, "pip install boto3  (or: python -m pip install -e '.[bedrock]')"))
        has_creds = any(os.environ.get(k) for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_WEB_IDENTITY_TOKEN_FILE"))
        out.append(("AWS credentials in env", has_creds, "set AWS_PROFILE (or key env vars / SSO login)"))
        out.append(("AWS region", bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")),
                    os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "defaults to us-east-1"))
        out.append(("model set", bool(_model(backend)), _model(backend) or "using dd-llm's default; set WORKGRAPH_MODEL to choose"))
    else:
        try:
            get_adapter(name)
            out.append((f"adapter `{name}` ready", True, "an adapter that needs a key or an SDK fails here when it is missing"))
        except Exception as e:      # missing SDK, missing API key: whatever the adapter says
            out.append((f"adapter `{name}` ready", False, str(e)[:160]))
    return out


def _claude_login() -> tuple[bool, str]:
    """Offline login check via `claude auth status` (reads local config, no model call)."""
    import json
    import subprocess
    try:
        r = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=30,
                           env=subscription_env())
        info = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False, "could not read `claude auth status`; run `claude` once to log in"
    ok = bool(info.get("loggedIn")) and info.get("authMethod") == "claude.ai"
    return ok, f"{info.get('authMethod')} / {info.get('subscriptionType') or 'no subscription'}" if ok else \
        f"not a subscription login (authMethod={info.get('authMethod')!r}); run `claude` and /login"
