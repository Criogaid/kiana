"""Classification is the only interchangeable external capability."""

from collections.abc import Sequence
from typing import Protocol

from .types import ClassifyOutcome, Msg, ThemeRule


class Classifier(Protocol):
    async def classify(
        self, msgs: Sequence[Msg], themes: Sequence[ThemeRule]
    ) -> ClassifyOutcome: ...
