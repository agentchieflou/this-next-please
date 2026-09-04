"""Positive: a branchy function many callers reach. Near-miss: an equally hot one-liner."""


def positive_hot_and_branchy(v):
    if v == 1:
        return "a"
    elif v == 2:
        return "b"
    elif v == 3:
        return "c"
    elif v == 4:
        return "d"
    elif v == 5:
        return "e"
    return "z"


def nearmiss_hot_but_simple(v):
    return v + 1


def c1(v):
    return positive_hot_and_branchy(v) + str(nearmiss_hot_but_simple(v))


def c2(v):
    return positive_hot_and_branchy(v) + str(nearmiss_hot_but_simple(v))


def c3(v):
    return positive_hot_and_branchy(v) + str(nearmiss_hot_but_simple(v))
