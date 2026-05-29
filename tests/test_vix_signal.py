"""TDD: VIX > 30 加仓信号(用于 NDX 监控)。"""

import pytest

from monitor import evaluate_vix_signal, VIX_THRESHOLD


def test_vix_above_threshold_triggers():
    assert evaluate_vix_signal(VIX_THRESHOLD + 0.01) is True


def test_vix_at_or_below_threshold_does_not_trigger():
    assert evaluate_vix_signal(VIX_THRESHOLD) is False
    assert evaluate_vix_signal(VIX_THRESHOLD - 0.01) is False


def test_vix_missing_returns_none():
    assert evaluate_vix_signal(None) is None
