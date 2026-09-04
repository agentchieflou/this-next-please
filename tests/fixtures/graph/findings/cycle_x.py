"""Positive half of a deliberate import cycle."""
import cycle_y


def x_uses_y():
    return cycle_y.y_value()
