"""G0.2 — the offline guarantee is a TEST, not a claim (spec-dependency-baseline.md §2.3).

`langsmith` (a telemetry client) is installed transitively by `langgraph` — 44 packages land, and
that one can phone home. The program's standing rule is "the suite runs offline with no
credentials", and a guarantee nobody re-checks is a guarantee that expires quietly.

Verified once by hand on 2026-09-01; this file makes it permanent.
"""
from __future__ import annotations

import os
import socket

import pytest

TRACING_ENV_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY",
                    "LANGCHAIN_API_KEY", "LANGCHAIN_ENDPOINT")


def test_no_tracing_env_var_is_set():
    """Opt-in telemetry must stay opted out. If one of these is set in CI, traces leave the machine."""
    enabled = {v: os.environ[v] for v in TRACING_ENV_VARS if os.environ.get(v)}
    assert not enabled, f"tracing/telemetry env vars are set: {sorted(enabled)}"


class _NonLoopbackBlocked(AssertionError):
    pass


@pytest.fixture()
def no_outbound_network(monkeypatch):
    """Raise on any connect() to a non-loopback address. Stdlib only — no new dependency to test
    that we have few dependencies."""
    real_connect = socket.socket.connect
    attempts: list = []

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if isinstance(host, str) and not (
            host.startswith("127.") or host in ("localhost", "::1", "0.0.0.0")
        ):
            attempts.append(address)
            raise _NonLoopbackBlocked(f"non-loopback connection attempted: {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield attempts


def test_importing_langgraph_makes_no_outbound_call(no_outbound_network):
    pytest.importorskip("langgraph.graph")
    assert no_outbound_network == []


def test_running_a_graph_makes_no_outbound_call(no_outbound_network):
    """The real check: build and run a graph end to end under the guard."""
    graph_mod = pytest.importorskip("langgraph.graph")
    from typing import TypedDict

    class S(TypedDict):
        n: int

    g = graph_mod.StateGraph(S)
    g.add_node("bump", lambda s: {"n": s["n"] + 1})
    g.add_edge(graph_mod.START, "bump")
    g.add_edge("bump", graph_mod.END)

    assert g.compile().invoke({"n": 0}) == {"n": 1}
    assert no_outbound_network == [], "a graph run attempted an outbound connection"


def test_the_guard_itself_actually_fires(no_outbound_network):
    """A guard that cannot fail proves nothing. Verify it rejects a real non-loopback address."""
    with pytest.raises(_NonLoopbackBlocked):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("93.184.216.34", 80))
    assert len(no_outbound_network) == 1
