"""A documented subset of git's ``.gitignore`` matching semantics.

Git's ignore engine (``wildmatch``) is not in the standard library, so the
scanner ships a small translation to regular expressions.  The supported subset
is exactly what ``docs/SCANNER_POLICY.md`` promises:

* blank lines and ``#`` comments are ignored (``\\#`` escapes a literal ``#``),
* ``!`` negates (a trailing match wins; ``\\!`` escapes a literal ``!``),
* a trailing ``/`` restricts a rule to directories,
* any other ``/`` (or a leading ``/``) anchors the rule to the directory that
  contains the ``.gitignore`` file,
* ``*`` and ``?`` never cross ``/``, ``**`` is special only as a whole path
  segment (``**/``, ``/**/``, ``/**``), character classes (``[a-z]``,
  ``[!0-9]``) and backslash escapes inside a class are supported,
* unescaped trailing spaces are stripped, escaped trailing spaces are literal.

Each ``.gitignore`` file is evaluated relative to its own directory.  Rules from
ancestor files are applied first and deeper files last, which implements
last-match-wins across the hierarchy.  The walker prunes ignored directories, so
a file under an ignored parent can never be re-included (matching git, which
also refuses to re-include children of an excluded directory).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Rule:
    """One compiled ``.gitignore`` line."""

    regex: re.Pattern[str]
    negated: bool
    dir_only: bool


@dataclass(frozen=True, slots=True)
class _IgnoreFile:
    """The rules parsed out of one ``.gitignore`` file and their base dir."""

    base: str
    rules: tuple[_Rule, ...]


class GitIgnoreMatcher:
    """Ordered collection of parsed ``.gitignore`` files for one scan."""

    def __init__(self) -> None:
        self._files: list[_IgnoreFile] = []

    def add(self, base: str, text: str) -> None:
        """Register one ignore file; *base* is its repo-relative POSIX dir."""

        self._files.append(parse_ignore_file(text, base=base))

    def is_ignored(self, rel_path: str, *, is_dir: bool) -> bool:
        """Return the final decision for a repo-relative path (last match wins)."""

        decision = False
        for ignore_file in self._files:
            base = ignore_file.base
            if base:
                prefix = base + "/"
                if not rel_path.startswith(prefix):
                    continue
                candidate = rel_path[len(prefix) :]
            else:
                candidate = rel_path
            for rule in ignore_file.rules:
                if rule.dir_only and not is_dir:
                    continue
                if rule.regex.fullmatch(candidate) is not None:
                    decision = not rule.negated
        return decision


def parse_ignore_file(text: str, *, base: str = "") -> _IgnoreFile:
    """Parse gitignore *text* into compiled rules rooted at *base*."""

    rules: list[_Rule] = []
    for raw_line in text.splitlines():
        line = _strip_trailing_spaces(raw_line)
        if not line:
            continue
        if line.startswith("#"):
            continue
        negated = False
        if line.startswith("!"):
            negated = True
            line = line[1:]
        dir_only = False
        if line.endswith("/") and not line.endswith("\\/"):
            dir_only = True
            line = line[:-1]
        if not line:
            continue
        anchored = "/" in line
        if line.startswith("/"):
            line = line[1:]
            anchored = True
        body = _translate(line)
        if not body:
            continue
        source = body if anchored else "(?:.*/)?" + body
        try:
            regex = re.compile(source)
        except re.error:  # pragma: no cover - translator is designed to be total
            continue
        rules.append(_Rule(regex=regex, negated=negated, dir_only=dir_only))
    return _IgnoreFile(base=base, rules=tuple(rules))


def _strip_trailing_spaces(line: str) -> str:
    """Remove trailing spaces that are not backslash-escaped (git behaviour)."""

    while line.endswith(" "):
        backslashes = 0
        index = len(line) - 2
        while index >= 0 and line[index] == "\\":
            backslashes += 1
            index -= 1
        if backslashes % 2:
            break
        line = line[:-1]
    return line


def _translate(body: str) -> str:
    """Translate one wildmatch pattern body into a regular-expression source."""

    out: list[str] = []
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if char == "\\":
            index += 1
            if index < length:
                out.append(re.escape(body[index]))
                index += 1
            else:
                out.append(re.escape("\\"))
            continue
        if char == "*":
            if body.startswith("**", index):
                before = body[index - 1 : index] if index else ""
                after = body[index + 2 : index + 3]
                if not before and after in ("", "/"):
                    if after == "/":
                        out.append("(?:.*/)?")
                        index += 3
                    else:
                        out.append(".*")
                        index += 2
                    continue
                if before == "/" and not after:
                    out.append(".*")
                    index += 2
                    continue
                if before == "/" and after == "/":
                    out.append("(?:.*/)?")
                    index += 3
                    continue
                # Consecutive asterisks that are not a whole segment behave
                # like regular asterisks.
                out.append("[^/]*")
                index += 2
                continue
            out.append("[^/]*")
            index += 1
            continue
        if char == "?":
            out.append("[^/]")
            index += 1
            continue
        if char == "[":
            translated, index = _translate_class(body, index)
            out.append(translated)
            continue
        out.append(re.escape(char))
        index += 1
    return "".join(out)


def _translate_class(body: str, start: int) -> tuple[str, int]:
    """Translate a character class starting at ``body[start] == '['``."""

    length = len(body)
    index = start + 1
    negated = False
    if index < length and body[index] in ("!", "^"):
        negated = True
        index += 1
    items: list[str] = []
    first = True
    while index < length:
        char = body[index]
        if char == "]" and not first:
            prefix = "[^" if negated else "["
            return prefix + "".join(items) + "]", index + 1
        if char == "\\" and index + 1 < length:
            items.append(re.escape(body[index + 1]))
            index += 2
            first = False
            continue
        if char == "-" and items and index + 1 < length and body[index + 1] != "]":
            items.append("-")
            index += 1
            first = False
            continue
        items.append(re.escape(char))
        index += 1
        first = False
    # Unterminated class: treat the "[" as a literal character.
    return re.escape("["), start + 1
