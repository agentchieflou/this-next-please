"""A slow implementation and a fast one, so a regression gate has something real to measure."""


def slow_version(items):
    """Membership against a list: O(n) per lookup."""
    seen = []
    hits = 0
    for it in items:
        if it in seen:
            hits += 1
        seen.append(it)
    return hits


def fast_version(items):
    """Same answer, via a set."""
    seen = set()
    hits = 0
    for it in items:
        if it in seen:
            hits += 1
        seen.add(it)
    return hits
