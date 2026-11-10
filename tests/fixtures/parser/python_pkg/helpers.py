"""Helpers for the fixture package."""

from .models import Base

LIMIT = 3


def helper(value):
    """Return the value unchanged."""
    return value


class Calculator(Base):
    def add(self, a, b):
        return helper(a) + helper(b)
