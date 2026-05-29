import pytest

from monitor import ma


def test_ma_returns_simple_average_of_last_n_closes():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert ma(closes, 5) == 3.0


def test_ma_uses_only_the_last_n_closes_when_more_data_available():
    closes = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    # last 5 = 20..60, avg = 40
    assert ma(closes, 5) == 40.0


def test_ma_returns_none_when_not_enough_data():
    assert ma([1.0, 2.0], 5) is None


def test_ma_works_on_120_and_250_window_sizes():
    closes = list(range(1, 251))  # 1..250
    # MA250 over 1..250 = 125.5
    assert ma(closes, 250) == pytest.approx(125.5)
    # MA120 = avg of 131..250 = (131+250)/2 = 190.5
    assert ma(closes, 120) == pytest.approx(190.5)
