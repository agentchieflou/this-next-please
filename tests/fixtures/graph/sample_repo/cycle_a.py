"""Part A of deliberate import cycle."""
import cycle_b

def func_a():
    return cycle_b.func_b()
