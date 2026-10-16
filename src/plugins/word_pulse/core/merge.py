"""Union literal and semantic evidence without duplicating the other category."""

from dataclasses import dataclass

from .types import OTHER, Label, Msg


@dataclass(frozen=True, slots=True)
class AIVerdict:
    relevant: bool
    cluster_ids: frozenset[int]


def merge(
    theme_id: int,
    msg: Msg,
    literal_relevant: bool,
    literal_hits: frozenset[int],
    ai: AIVerdict | None,
) -> list[Label]:
    clusters = literal_hits | (ai.cluster_ids if ai else frozenset())
    if clusters:
        return [
            Label(
                theme_id,
                msg.archive_id,
                cluster,
                "literal" if cluster in literal_hits else "ai",
                msg.user_id,
                msg.event_time,
            )
            for cluster in sorted(clusters)
        ]
    if literal_relevant or (ai is not None and ai.relevant):
        return [
            Label(
                theme_id,
                msg.archive_id,
                OTHER,
                "literal" if literal_relevant else "ai",
                msg.user_id,
                msg.event_time,
            )
        ]
    return []
