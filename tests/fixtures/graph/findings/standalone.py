"""Near-miss for import-cycle: a module that imports one of the pair without closing a ring."""
import cycle_y


def only_imports():
    return cycle_y.y_value()
