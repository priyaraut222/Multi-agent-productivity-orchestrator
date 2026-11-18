"""Importing this module registers every tool (import side effects) and returns the registry."""
from tools import (calendar_tools, email_tools, github_tools, memory_tools, planning_tools,  # noqa: F401
                   research_tools, task_tools)
from tools.registry import REGISTRY


def load() -> dict:
    return REGISTRY
