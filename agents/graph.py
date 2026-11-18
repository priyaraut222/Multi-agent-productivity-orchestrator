"""A tiny LangGraph-style state-graph engine (pure Python, no dependency).

Nodes are functions ``state -> dict`` (partial state updates).  Edges may be static or
conditional (a router function returns the next node name).  Cycles are allowed (e.g. the
supervisor's execute-loop and the critic's revise-loop) and bounded by ``recursion_limit``.
"""
from __future__ import annotations

from typing import Callable

END = "__end__"


class GraphError(RuntimeError):
    pass


class StateGraph:
    def __init__(self, name: str = "graph"):
        self.name = name
        self.nodes: dict[str, Callable[[dict], dict | None]] = {}
        self.edges: dict[str, str] = {}
        self.conditional: dict[str, tuple[Callable[[dict], str], list[str]]] = {}
        self.entry: str | None = None

    def add_node(self, name: str, fn: Callable[[dict], dict | None]) -> "StateGraph":
        self.nodes[name] = fn
        return self

    def set_entry(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, router: Callable[[dict], str], targets: list[str]) -> "StateGraph":
        self.conditional[src] = (router, targets)
        return self

    def compile(self) -> "StateGraph":
        if not self.entry or self.entry not in self.nodes:
            raise GraphError("entry node missing")
        known = set(self.nodes) | {END}
        for src, dst in self.edges.items():
            if src not in self.nodes or dst not in known:
                raise GraphError(f"bad edge {src}->{dst}")
        for src, (_, targets) in self.conditional.items():
            if src not in self.nodes or any(t not in known for t in targets):
                raise GraphError(f"bad conditional edge from {src}")
        for n in self.nodes:
            if n not in self.edges and n not in self.conditional:
                raise GraphError(f"node '{n}' has no outgoing edge")
        return self

    def run(self, state: dict, on_event: Callable[[str, str, dict], None] | None = None,
            recursion_limit: int = 30) -> dict:
        current, steps = self.entry, 0
        while current != END:
            steps += 1
            if steps > recursion_limit:
                raise GraphError(f"recursion limit {recursion_limit} reached at '{current}'")
            if on_event:
                on_event("node_start", current, {})
            update = self.nodes[current](state) or {}
            state.update(update)
            state.setdefault("_path", []).append(current)
            if current in self.conditional:
                router, targets = self.conditional[current]
                nxt = router(state)
                if nxt not in targets:
                    raise GraphError(f"router at '{current}' returned unexpected '{nxt}'")
                current = nxt
            else:
                current = self.edges[current]
        return state

    def to_dot(self) -> str:
        lines = [f'digraph "{self.name}" {{', "  rankdir=LR;", '  node [shape=box, style="rounded,filled", fillcolor="#eef2ff", fontname="Helvetica"];',
                 '  START [shape=circle, fillcolor="#bbf7d0"]; END [shape=doublecircle, fillcolor="#fecaca"];',
                 f"  START -> {self.entry};"]
        for s, d in self.edges.items():
            lines.append(f"  {s} -> {'END' if d == END else d};")
        for s, (_, targets) in self.conditional.items():
            for t in targets:
                lines.append(f'  {s} -> {"END" if t == END else t} [style=dashed];')
        lines.append("}")
        return "\n".join(lines)
