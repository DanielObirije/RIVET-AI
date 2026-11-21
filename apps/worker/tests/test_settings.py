import pytest

from settings import (
    DEFAULT_AWS_REGION,
    DEFAULT_POOL_MAX_SIZE,
    DEFAULT_POOL_MIN_SIZE,
    DEFAULT_SQS_MAX_MESSAGES,
    DEFAULT_SQS_VISIBILITY_TIMEOUT,
    DEFAULT_SQS_WAIT_TIME_SECONDS,
    RECLAIM_MARGIN_SECONDS,
    load_deepseek_settings,
    load_queue_settings,
    load_storage_settings,
    pool_sizes,
    reclaim_seconds,
)

ENV_NAMES = (
    "SQS_QUEUE_URL",
    "AWS_REGION",
    "SQS_ENDPOINT_URL",
    "SQS_WAIT_TIME_SECONDS",
    "SQS_VISIBILITY_TIMEOUT",
    "SQS_MAX_MESSAGES",
    "S3_BUCKET_NAME",
    "S3_REGION",
    "S3_ENDPOINT_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DB_POOL_MIN_SIZE",
    "DB_POOL_MAX_SIZE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_queue_defaults_are_safe_without_any_configuration() -> None:
    settings = load_queue_settings()

    assert settings.queue_url is None
    assert settings.region == DEFAULT_AWS_REGION
    assert settings.endpoint_url is None
    assert settings.wait_time_seconds == DEFAULT_SQS_WAIT_TIME_SECONDS
    assert settings.visibility_timeout == DEFAULT_SQS_VISIBILITY_TIMEOUT
    assert settings.max_messages == DEFAULT_SQS_MAX_MESSAGES


def test_queue_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQS_QUEUE_URL", "http://localhost:4566/000000000000/rivet-jobs")
    monkeypatch.setenv("SQS_ENDPOINT_URL", "http://localhost:4566")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("SQS_WAIT_TIME_SECONDS", "5")
    monkeypatch.setenv("SQS_VISIBILITY_TIMEOUT", "90")
    monkeypatch.setenv("SQS_MAX_MESSAGES", "2")

    settings = load_queue_settings()

    assert settings.queue_url.endswith("/rivet-jobs")
    assert settings.endpoint_url == "http://localhost:4566"
    assert settings.region == "eu-west-1"
    assert settings.wait_time_seconds == 5
    assert settings.visibility_timeout == 90
    assert settings.max_messages == 2


def test_a_non_numeric_timeout_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQS_VISIBILITY_TIMEOUT", "two minutes")

    with pytest.raises(ValueError, match="SQS_VISIBILITY_TIMEOUT"):
        load_queue_settings()


def test_storage_region_falls_back_to_the_aws_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert load_storage_settings().bucket is None
    assert load_storage_settings().region == DEFAULT_AWS_REGION

    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    assert load_storage_settings().region == "eu-west-1"


def test_storage_region_prefers_its_own_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "rivet-assets")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("S3_REGION", "eu-west-1")

    settings = load_storage_settings()

    assert settings.bucket == "rivet-assets"
    assert settings.region == "eu-west-1"


def test_pool_sizes_default_to_one_held_connection() -> None:
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


def test_a_claim_is_owned_for_the_visibility_timeout() -> None:
    assert reclaim_seconds() == DEFAULT_SQS_VISIBILITY_TIMEOUT - RECLAIM_MARGIN_SECONDS


def test_a_shorter_visibility_timeout_shortens_the_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQS_VISIBILITY_TIMEOUT", "300")

    assert reclaim_seconds() == 300 - RECLAIM_MARGIN_SECONDS

    monkeypatch.setenv("SQS_VISIBILITY_TIMEOUT", "3")

    assert reclaim_seconds() == 1


def test_deepseek_settings_default_to_the_chat_model() -> None:
    settings = load_deepseek_settings()

    assert settings.api_key is None
    assert settings.model == "deepseek-chat"
