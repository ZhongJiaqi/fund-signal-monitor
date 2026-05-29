"""with_retry 包装器:akshare/Yahoo 偶尔失败时指数退避重试。"""

import pytest

from monitor import with_retry


def test_returns_value_on_first_success():
    """成功一次就不再重试,返回值穿透。"""
    calls = []

    def f():
        calls.append(1)
        return 'ok'

    assert with_retry(f, max_attempts=3, base_delay=0) == 'ok'
    assert len(calls) == 1


def test_retries_until_success():
    """前两次失败,第三次成功 → 总共调用 3 次,返回成功结果。"""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError('boom')
        return 'ok'

    assert with_retry(flaky, max_attempts=3, base_delay=0) == 'ok'
    assert len(calls) == 3


def test_raises_after_max_attempts():
    """耗尽次数后抛最后一次的异常,调用次数等于 max_attempts。"""
    calls = []

    def always_fail():
        calls.append(1)
        raise RuntimeError(f'attempt-{len(calls)}')

    with pytest.raises(RuntimeError, match='attempt-3'):
        with_retry(always_fail, max_attempts=3, base_delay=0)
    assert len(calls) == 3


def test_uses_exponential_backoff(monkeypatch):
    """重试间隔指数增长:base*1, base*2, base*4(失败 3 次 → sleep 2 次,因为最后一次不再 sleep)。"""
    sleeps = []
    monkeypatch.setattr('monitor.time.sleep', lambda s: sleeps.append(s))

    def always_fail():
        raise RuntimeError('boom')

    with pytest.raises(RuntimeError):
        with_retry(always_fail, max_attempts=3, base_delay=1)

    # 失败 3 次,在第 1、2 次失败后 sleep(总 2 次),最后一次失败直接抛
    assert sleeps == [1, 2]


def test_zero_delay_no_sleep(monkeypatch):
    """base_delay=0 不应调用 sleep(测试场景常用)。"""
    sleeps = []
    monkeypatch.setattr('monitor.time.sleep', lambda s: sleeps.append(s))

    def always_fail():
        raise RuntimeError('boom')

    with pytest.raises(RuntimeError):
        with_retry(always_fail, max_attempts=2, base_delay=0)
    assert sleeps == []
