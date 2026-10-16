"""Immutable message projections, rules, and classification results."""

from collections import Counter
from dataclasses import dataclass
from typing import Literal

type ThemeMode = Literal["semantic", "literal"]
type LabelSource = Literal["literal", "ai"]
OTHER = 0


@dataclass(frozen=True, slots=True)
class ClusterRule:
    id: int
    name: str
    aliases: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class ThemeRule:
    id: int
    group_id: str
    name: str
    mode: ThemeMode
    rules_version: int
    backfill_version: int
    backfill_next_id: int | None
    backfill_until_id: int | None
    clusters: tuple[ClusterRule, ...]


@dataclass(frozen=True, slots=True)
class Msg:
    archive_id: int
    event_time: int
    user_id: str
    text: str


@dataclass(frozen=True, slots=True)
class Label:
    theme_id: int
    archive_id: int
    cluster_id: int
    source: LabelSource
    user_id: str
    event_time: int


@dataclass(frozen=True, slots=True)
class ClassifyOutcome:
    labels: tuple[Label, ...]
    unclassified: dict[tuple[int, str], int]

    def __or__(self, other: "ClassifyOutcome") -> "ClassifyOutcome":
        counts = Counter(self.unclassified)
        counts.update(other.unclassified)
        return ClassifyOutcome(self.labels + other.labels, dict(counts))


EMPTY_OUTCOME = ClassifyOutcome((), {})
