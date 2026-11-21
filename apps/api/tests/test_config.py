import pytest

from app.config import (
    DEFAULT_POOL_MAX_SIZE,
    DEFAULT_POOL_MIN_SIZE,
    pool_sizes,
)


def test_pool_sizes_default_to_the_shared_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DB_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)

    assert pool_sizes() == (DEFAULT_POOL_MIN_SIZE, DEFAULT_POOL_MAX_SIZE)


def test_pool_sizes_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "4")

    assert pool_sizes() == (2, 4)


def test_a_pool_minimum_above_the_maximum_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "9")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "4")

    with pytest.raises(ValueError, match="DB_POOL_MIN_SIZE"):
        pool_sizes()


def test_a_non_numeric_pool_size_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "eight")

    with pytest.raises(ValueError, match="DB_POOL_MAX_SIZE"):
        pool_sizes()
