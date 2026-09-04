"""Positive: I/O inside a loop. Near-miss: the same I/O hoisted above the loop."""


def read_config(path):
    with open(path) as f:
        return f.read()


def positive_io_in_loop(paths):
    out = []
    for p in paths:
        out.append(read_config(p))
    return out


def nearmiss_io_hoisted(paths):
    blob = read_config(paths[0])
    out = []
    for p in paths:
        out.append(blob + p)
    return out
