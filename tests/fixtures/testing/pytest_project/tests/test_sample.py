import pytest


def test_pass():
    assert 1 == 1


def test_fail():
    assert 1 == 2


@pytest.mark.skip(reason="skipping test")
def test_skip():
    pass
