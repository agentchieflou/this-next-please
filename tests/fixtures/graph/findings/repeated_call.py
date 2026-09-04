"""Positive: the same call twice with the same args. Near-miss: an assignment in between."""


def expensive(key):
    return len(key) * 2


def positive_repeated_call(key):
    a = expensive(key)
    b = expensive(key)
    return a + b


def nearmiss_rebound_between(key):
    a = expensive(key)
    key = key + "!"
    b = expensive(key)
    return a + b
