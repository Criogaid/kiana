"""Mine residual Chinese phrases using document support, PMI and boundary entropy."""

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .text import normalize
from .types import Msg, ThemeRule

MIN_MESSAGES = 3
MIN_USERS = 2
MAX_RESULTS = 20
MAX_PHRASE_CHARS = 6
MAX_LAYER_PHRASES = 20000
_HAN_RUN = re.compile(r"[㐀-䶿一-鿿]+")
_STOP_PHRASES = frozenset(
    [
        "一个",
        "一下",
        "不会",
        "不是",
        "什么",
        "他们",
        "但是",
        "你们",
        "可以",
        "只是",
        "可能",
        "大家",
        "今天",
        "如果",
        "已经",
        "应该",
        "我们",
        "所以",
        "时候",
        "昨天",
        "然后",
        "现在",
        "真的",
        "知道",
        "自己",
        "这个",
        "这么",
        "这里",
        "那个",
        "那里",
        "还是",
        "非常",
        "感觉",
    ]
)


@dataclass(frozen=True, slots=True)
class CandidatePhrase:
    phrase: str
    message_count: int
    user_count: int


@dataclass(frozen=True, slots=True)
class _Residual:
    message_id: int
    user_id: str
    segments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Scored:
    phrase: str
    messages: frozenset[int]
    users: int
    score: float


def _substrings(text: str) -> set[str]:
    return {
        text[start : start + length]
        for length in range(2, min(MAX_PHRASE_CHARS, len(text)) + 1)
        for start in range(len(text) - length + 1)
    }


def _residuals(theme: ThemeRule, messages: Sequence[Msg]) -> tuple[list[_Residual], set[str]]:
    known = {normalize(theme.name)} | {
        normalize(name) for cluster in theme.clusters for name in (cluster.name, *cluster.aliases)
    }
    pattern = re.compile("|".join(re.escape(name) for name in sorted(known, key=len, reverse=True)))
    rows = [
        _Residual(
            msg.archive_id,
            msg.user_id,
            tuple(
                segment
                for part in pattern.split(normalize(msg.text))
                for segment in _HAN_RUN.findall(part)
            ),
        )
        for msg in messages
    ]
    return rows, {part for name in known for part in _substrings(name)}


def _frequent(rows: Sequence[_Residual]) -> set[str]:
    frequent: set[str] = set()
    shorter: set[str] = set()
    for length in range(2, MAX_PHRASE_CHARS + 1):
        counts: Counter[str] = Counter()
        for row in rows:
            seen = {
                segment[start : start + length]
                for segment in row.segments
                for start in range(len(segment) - length + 1)
            }
            counts.update(
                phrase
                for phrase in seen
                if length == 2 or (phrase[:-1] in shorter and phrase[1:] in shorter)
            )
        passed = [phrase for phrase, count in counts.items() if count >= MIN_MESSAGES]
        passed.sort(key=lambda phrase: (-counts[phrase], phrase))
        shorter = set(passed[:MAX_LAYER_PHRASES])
        if not shorter:
            break
        frequent |= shorter
    return frequent


@dataclass(slots=True)
class _Measurements:
    occurrences: dict[str, int]
    totals: Counter[int]
    left: dict[str, Counter[str]]
    right: dict[str, Counter[str]]
    documents: dict[str, set[int]]
    users: dict[str, set[str]]


def _measure(rows: Sequence[_Residual], candidates: set[str]) -> _Measurements:
    needed = candidates | {
        part
        for phrase in candidates
        for split in range(1, len(phrase))
        for part in (phrase[:split], phrase[split:])
    }
    result = _Measurements(
        dict.fromkeys(needed, 0),
        Counter(),
        defaultdict(Counter),
        defaultdict(Counter),
        defaultdict(set),
        defaultdict(set),
    )
    for row in rows:
        for segment in row.segments:
            for length in range(1, MAX_PHRASE_CHARS + 1):
                result.totals[length] += max(0, len(segment) - length + 1)
                for start in range(len(segment) - length + 1):
                    phrase = segment[start : start + length]
                    if phrase in needed:
                        result.occurrences[phrase] += 1
                    if phrase in candidates:
                        end = start + length
                        result.left[phrase][segment[start - 1] if start else "^"] += 1
                        result.right[phrase][segment[end] if end < len(segment) else "$"] += 1
                        result.documents[phrase].add(row.message_id)
                        result.users[phrase].add(row.user_id)
    return result


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _pmi(phrase: str, data: _Measurements) -> float:
    probability = data.occurrences[phrase] / data.totals[len(phrase)]
    return min(
        math.log2(
            probability
            / (
                data.occurrences[phrase[:split]]
                / data.totals[split]
                * data.occurrences[phrase[split:]]
                / data.totals[len(phrase) - split]
            )
        )
        for split in range(1, len(phrase))
    )


def discover_candidates(theme: ThemeRule, messages: Sequence[Msg]) -> tuple[CandidatePhrase, ...]:
    """Mine already-selected AI-only messages; counts deduplicate messages and users."""
    rows, known = _residuals(theme, messages)
    candidates = {
        phrase
        for phrase in _frequent(rows)
        if phrase not in known and phrase not in _STOP_PHRASES and len(set(phrase)) > 1
    }
    data = _measure(rows, candidates)
    scores = [
        _Scored(
            phrase,
            frozenset(data.documents[phrase]),
            len(data.users[phrase]),
            _pmi(phrase, data)
            + min(_entropy(data.left[phrase]), _entropy(data.right[phrase]))
            + math.log2(len(data.documents[phrase])),
        )
        for phrase in candidates
        if len(data.documents[phrase]) >= MIN_MESSAGES and len(data.users[phrase]) >= MIN_USERS
    ]
    scores.sort(key=lambda item: (-len(item.phrase), -item.score, item.phrase))
    absorbed: dict[str, set[frozenset[int]]] = defaultdict(set)
    kept: list[_Scored] = []
    for item in scores:
        if item.messages in absorbed[item.phrase]:
            continue
        for part in _substrings(item.phrase) - {item.phrase}:
            absorbed[part].add(item.messages)
        kept.append(item)
    kept.sort(key=lambda item: (-item.score, -len(item.messages), -len(item.phrase), item.phrase))
    return tuple(
        CandidatePhrase(item.phrase, len(item.messages), item.users) for item in kept[:MAX_RESULTS]
    )
