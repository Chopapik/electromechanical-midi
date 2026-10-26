"""Public deterministic arrangement entry point; no transport or UI dependency."""
from .planning_pipeline import run


def arrange(source, registry):
    return run(source, registry)
