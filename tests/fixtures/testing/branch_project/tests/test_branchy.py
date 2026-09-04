import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.branchy import check_value


def test_positive():
    assert check_value(5) == 1
