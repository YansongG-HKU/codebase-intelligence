"""Data models for the fixture package."""

class Base:
    """Base class."""

    def describe(self):
        return helper_text("base")


class User(Base):
    ROLE = "user"

    def describe(self):
        return helper_text(self.ROLE)


def helper_text(value):
    return value


cache = {}
