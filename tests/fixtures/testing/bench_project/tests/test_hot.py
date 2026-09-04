import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.hot import fast_version, slow_version

DATA = [i % 400 for i in range(4000)]


def test_slow_version():
    assert slow_version(DATA) == 3600


def test_fast_version():
    assert fast_version(DATA) == 3600
