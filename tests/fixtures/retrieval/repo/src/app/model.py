"""Bounded context model."""


class ContextPack:
    """Immutable context pack for one task."""

    def __init__(self, task, items):
        self.task = task
        self.items = items

    def total_tokens(self):
        return sum(item.tokens_estimated for item in self.items)
