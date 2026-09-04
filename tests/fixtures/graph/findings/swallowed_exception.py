"""Positive: a broad except whose body is pass. Near-miss: a narrow except that returns a fallback."""


def positive_swallowed(path):
    try:
        return open(path).read()
    except Exception:
        pass


def nearmiss_handled(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return ""
