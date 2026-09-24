import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.hot import fast_version, slow_version

DATA = [i % 8000 for i in range(16000)]


def test_slow_version():
    assert slow_version(DATA) == 8000


def test_fast_version():
    assert fast_version(DATA) == 8000
