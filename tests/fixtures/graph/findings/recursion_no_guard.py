"""Positive: a self-call with no conditional exit. Near-miss: the same with a base case."""


def positive_unguarded(n):
    return positive_unguarded(n - 1)


def nearmiss_guarded(n):
    if n <= 0:
        return 0
    return nearmiss_guarded(n - 1)
