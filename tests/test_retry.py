"""Тесты политики retry: успех, повторы, исчерпание попыток, backoff."""

import pytest

from generator.retry import RetryError, RetryPolicy


def test_succeeds_on_first_attempt() -> None:
    calls: list[int] = []

    def fn() -> int:
        calls.append(1)
        return 42

    policy = RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=1.0)
    assert policy.execute(fn) == 42
    assert len(calls) == 1


def test_retries_then_succeeds() -> None:
    calls: list[int] = []
    slept: list[float] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("db down")
        return "ok"

    policy = RetryPolicy(
        max_attempts=5, base_delay=0.0, max_delay=1.0, sleep=slept.append
    )
    assert policy.execute(fn) == "ok"
    assert len(calls) == 3
    assert len(slept) == 2


def test_exhausts_attempts_and_raises_retry_error() -> None:
    calls: list[int] = []

    def fn() -> None:
        calls.append(1)
        raise ConnectionError("boom")

    policy = RetryPolicy(
        max_attempts=3, base_delay=0.0, max_delay=1.0, sleep=lambda _: None
    )
    with pytest.raises(RetryError):
        policy.execute(fn)
    assert len(calls) == 3


def test_backoff_grows_exponentially() -> None:
    delays: list[float] = []

    def fn() -> None:
        raise ConnectionError("boom")

    policy = RetryPolicy(
        max_attempts=4,
        base_delay=1.0,
        max_delay=100.0,
        backoff_factor=2.0,
        jitter=0.0,
        sleep=delays.append,
    )
    with pytest.raises(RetryError):
        policy.execute(fn)
    assert delays == [1.0, 2.0, 4.0]
