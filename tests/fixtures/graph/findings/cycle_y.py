"""Other half of the deliberate import cycle."""
import cycle_x


def y_value():
    return 1


def y_uses_x():
    return cycle_x.x_uses_y()
