"""Positive: a function nothing calls. Near-miss: one reached only through getattr."""


def positive_dead():
    return 1


def nearmiss_dynamic():
    return 2


def dispatch(mod, name):
    return getattr(mod, "nearmiss_dynamic")()
