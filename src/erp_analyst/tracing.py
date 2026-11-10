"""Runs a compiled LangGraph graph while timing each node, using
`stream_mode="updates"` rather than a single `invoke()` — the only way to
see per-node boundaries without LangGraph's own tracing integration
(Langfuse, LangSmith), which needs a hosted account/API key this
environment doesn't have (see KNOWN_LIMITS.md). Pure orchestration, no I/O
of its own, so it's testable against the same fake generator/executor
pattern the rest of the agent tests use.
"""
from __future__ import annotations

import time
from typing import Any


def run_with_timings(graph: Any, input_state: Any, config: dict | None = None) -> tuple[dict, dict[str, float], dict | None]:
    """Returns (final_state, {node_name: elapsed_ms}, interrupt_payload).

    interrupt_payload is the dict passed to `interrupt(...)` in the graph
    (e.g. {"question": "..."}) if the run paused, else None. final_state
    accumulates every node's returned keys in execution order, same as
    what `graph.invoke()` would hand back. `input_state` is either the
    initial state dict, or a `Command(resume=...)` when continuing a
    previously-interrupted run — in the latter case there's no prior
    state to seed from; the caller already has it from the first call.
    """
    node_timings: dict[str, float] = {}
    final_state: dict = dict(input_state) if isinstance(input_state, dict) else {}
    interrupt_payload: dict | None = None
    last_t = time.perf_counter()

    for update in graph.stream(input_state, config=config, stream_mode="updates"):
        now = time.perf_counter()
        elapsed_ms = (now - last_t) * 1000
        last_t = now
        for node_name, node_output in update.items():
            if node_name == "__interrupt__":
                # node_output is a tuple of Interrupt objects in real
                # LangGraph; each has a `.value` carrying what was passed
                # to interrupt(). Only one clarify node exists, so only
                # one interrupt can fire per run.
                interrupt_payload = node_output[0].value if node_output else None
                continue
            node_timings[node_name] = node_timings.get(node_name, 0.0) + elapsed_ms
            if isinstance(node_output, dict):
                final_state.update(node_output)

    return final_state, node_timings, interrupt_payload
