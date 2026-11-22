"""The LLM seam: every backend is a dd-llm adapter; what workgraph adds is the names, the resolution order, and the stop-on-limit."""
import subprocess

import pytest

from workgraph import llm


class _Done:
    def __init__(self, rc=0, out=b"hello", err=b""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_names_map_to_dd_llm_adapters():
    assert llm.adapter_name("cc_cli") == "claude_cli" and llm.adapter_name("claude-cli") == "claude_cli"
    assert llm.adapter_name("claude") == "anthropic" and llm.adapter_name("bedrock") == "bedrock"
    assert llm.resolve_backend("echo") == "echo"                       # any dd-llm name is accepted


def test_strips_billing_vars_and_uses_stdin(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return _Done()

    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDECODE", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "AWS_PROFILE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("WORKGRAPH_CC_MODEL", "m1")
    monkeypatch.delenv("WORKGRAPH_MODEL", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert llm.complete("the prompt", backend="cc_cli") == "hello"
    assert seen["input"] == b"the prompt" and "the prompt" not in seen["cmd"]                 # via stdin, not argv
    assert seen["cmd"][-2:] == ["--tools", ""] and seen["cmd"][seen["cmd"].index("--model") + 1] == "m1"
    assert not (llm.STRIP_VARS & set(seen["env"])) and seen["env"]["AWS_PROFILE"] == "x"      # subscription only; unrelated vars pass


def test_model_and_timeout_come_from_the_environment(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, **kw) or _Done())
    monkeypatch.delenv("WORKGRAPH_CC_MODEL", raising=False)
    monkeypatch.setenv("WORKGRAPH_MODEL", "m2")
    monkeypatch.setenv("WORKGRAPH_CC_TIMEOUT", "77")
    llm.complete("p", backend="cc_cli")
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "m2" and seen["timeout"] == 77


def test_allowed_tools_replaces_tools_off(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd) or _Done())
    llm.complete("p", backend="cc_cli", allowed_tools=["WebSearch", "Read"])
    assert "--allowedTools" in seen["cmd"] and "WebSearch,Read" in seen["cmd"] and "--tools" not in seen["cmd"]


def test_limit_error_is_distinct_and_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(1) or _Done(1, b"Session limit reached"))
    with pytest.raises(llm.BackendLimitError):
        llm.complete("p", backend="cc_cli")
    assert len(calls) == 1


def test_launch_errors_retry_but_timeouts_do_not(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    n = {"c": 0}

    def flaky(*a, **k):
        n["c"] += 1
        if n["c"] < 3:
            raise FileNotFoundError("claude")
        return _Done()

    monkeypatch.setattr(subprocess, "run", flaky)
    assert llm.complete("p", backend="cc_cli") == "hello" and n["c"] == 3                   # rode out the updater race

    def hang(*a, **k):
        n["c"] += 1
        raise subprocess.TimeoutExpired("claude", 1)

    n["c"] = 0
    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="timed out"):
        llm.complete("p", backend="cc_cli")
    assert n["c"] == 1


def test_any_other_backend_goes_through_its_dd_llm_adapter():
    assert llm.complete("ping", backend="echo")                         # dd-llm's echo adapter answers without a model
    assert [c for c in llm.check_backend("echo")][0][1] is True
