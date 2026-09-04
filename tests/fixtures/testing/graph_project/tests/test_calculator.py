import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.calculator import add, subtract


def test_add():
    assert add(1, 2) == 3


def test_subtract():
    assert subtract(5, 2) == 3
