"""Regenerate TOOLS.md from the live tool registry:  python scripts/gen_tools_doc.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.specialists import SPECIALISTS  # noqa: E402
from tools import loader  # noqa: E402
from tools.registry import REGISTRY  # noqa: E402

loader.load()
ICON = {"read": "🟢 read", "write": "🟡 write", "external": "🔴 external (approval)"}
lines = ["# Tool catalogue", "", "Generated from the tool registry. Risk levels drive the human-in-the-loop policy:",
         "🟢 read = always allowed · 🟡 write = changes local data · 🔴 external = affects other people/services, queued for approval.", ""]
for agent in SPECIALISTS.values():
    lines += [f"## {agent.title}", "", agent.description, "", "| Tool | Risk | Purpose |", "|---|---|---|"]
    groups = set(agent.groups + ["memory"])
    for t in REGISTRY.values():
        if t.group in groups:
            risk = t.risk if isinstance(t.risk, str) else "write / external (depends on arguments)"
            lines.append(f"| `{t.signature()}` | {ICON.get(risk, risk)} | {t.description} |")
    lines.append("")
open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "TOOLS.md"), "w").write("\n".join(lines))
print("TOOLS.md written")
