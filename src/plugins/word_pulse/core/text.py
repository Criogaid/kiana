"""Normalized literal matching and message noise filtering."""

import re
import unicodedata

from .types import ThemeRule


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def is_noise(text: str, user_id: str, *, self_id: str) -> bool:
    value = normalize(text)
    return (
        user_id == self_id
        or len(value) < 2
        or not any(char.isalnum() for char in value)
        or value.startswith(("词频", "/"))
    )


class LiteralMatcher:
    """Prefer the longest writing at each start; retain hits at different positions."""

    def __init__(self, theme: ThemeRule):
        self._owners: dict[str, set[int]] = {}
        self._owners[normalize(theme.name)] = set()
        for cluster in theme.clusters:
            for writing in (cluster.name, *cluster.aliases):
                self._owners.setdefault(normalize(writing), set()).add(cluster.id)
        self._owners.pop("", None)
        alternatives = []
        for writing in sorted(self._owners, key=lambda item: (-len(item), item)):
            escaped = re.escape(writing)
            if re.fullmatch("[a-z0-9]+", writing):
                escaped = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
            alternatives.append(escaped)
        self._pattern = re.compile("(?=(" + "|".join(alternatives) + "))") if alternatives else None

    def match(self, text: str) -> tuple[bool, frozenset[int]]:
        if self._pattern is None:
            return False, frozenset()
        relevant = False
        hits: set[int] = set()
        for match in self._pattern.finditer(normalize(text)):
            relevant = True
            hits.update(self._owners[match[1]])
        return relevant, frozenset(hits)
