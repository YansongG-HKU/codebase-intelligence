"""Absolute-import fixture."""

from python_pkg.models import Base


def build():
    return Base()
