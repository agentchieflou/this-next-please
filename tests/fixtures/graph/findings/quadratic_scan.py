"""Positive: membership against a list local inside a loop. Near-miss: the same via a set."""


def positive_quadratic_scan(items):
    seen = []
    hits = 0
    for it in items:
        if it in seen:
            hits += 1
    return hits


def nearmiss_set_membership(items):
    seen = set()
    hits = 0
    for it in items:
        if it in seen:
            hits += 1
    return hits
