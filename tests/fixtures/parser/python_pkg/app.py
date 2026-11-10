"""Application entry points."""

import os

import python_pkg.helpers
from .helpers import Calculator, helper
from .missing import ghost
from .models import Base
from python_pkg.ghost import phantom


class App(Base):
    def run(self):
        calc = Calculator()
        return calc.add(1, 2)


def main():
    app = App()
    return app.run()
