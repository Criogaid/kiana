"""Allocate message-count budgets without exceeding the remaining allowance."""


def take(budget_left: int, wanted: int) -> int:
    return max(0, min(budget_left, wanted))
