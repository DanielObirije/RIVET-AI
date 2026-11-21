from botocore.exceptions import EndpointConnectionError

from jobs import get_attachment, get_job
from processor import Outcome, process_job
from samples import jpeg_bytes, pdf_bytes
from settings import DeepSeekSettings


def test_document_text_is_added_to_the_user_turn(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(
        filename="notes.pdf",
        content_type="application/pdf",
        body=pdf_bytes("Hello PDF"),
    )
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "Summary")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert outcome is Outcome.DONE
    messages = calls[-1]["messages"]
    assert "Hello PDF" in messages[-1][1]
    assert get_job(job_id, dsn=dsn).result == "Summary"

    cached = get_attachment(attachment_id, dsn=dsn)
    assert cached is not None
    assert cached.extracted_text is not None
    assert "Hello PDF" in cached.extracted_text


def test_cached_text_is_reused_without_a_download(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(extracted_text="cached body")
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "Summary")

    process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert fake_s3.get_calls == []
    assert "cached body" in calls[-1]["messages"][-1][1]


def test_an_image_goes_to_a_vision_model(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(
        filename="photo.jpg",
        content_type="image/jpeg",
        body=jpeg_bytes(),
    )
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "A photo")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-flash"),
        client=fake_s3,
    )

    assert outcome is Outcome.DONE
    assert calls[-1]["image_data_url"].startswith("data:image/jpeg;base64,")
    assert "photo.jpg" in calls[-1]["messages"][-1][1]


def test_an_image_is_refused_on_a_text_only_model(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(
        filename="photo.jpg",
        content_type="image/jpeg",
        body=jpeg_bytes(),
    )
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "never called")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert outcome is Outcome.DONE
    assert calls == []
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "image_unsupported"


def test_an_unreadable_document_fails_permanently(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(content_type="application/pdf", body=b"not a pdf")
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "never called")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert outcome is Outcome.DONE
    assert calls == []
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.error_code == "attachment_unreadable"


def test_a_missing_attachment_fails_permanently(
    dsn, queue_job, fake_s3, stub_completion
) -> None:
    job_id = queue_job(attachment_id="does-not-exist")
    calls = stub_completion(lambda: "never called")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert outcome is Outcome.DONE
    assert calls == []
    assert get_job(job_id, dsn=dsn).error_code == "attachment_missing"


def test_a_pending_attachment_is_refused(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(status="pending")
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "never called")

    process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert calls == []
    assert get_job(job_id, dsn=dsn).error_code == "attachment_missing"


def test_a_storage_failure_leaves_the_job_for_redelivery(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(extracted_text=None)
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "never called")
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert outcome is Outcome.RETRY
    assert calls == []
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "queued"


def test_an_oversized_object_fails_permanently(
    dsn, queue_job, attachment, fake_s3, stub_completion
) -> None:
    attachment_id = attachment(
        content_type="application/pdf", body=b"%PDF-" + b"x" * (1024 * 1024)
    )
    job_id = queue_job(attachment_id=attachment_id)
    calls = stub_completion(lambda: "never called")

    outcome = process_job(
        job_id,
        dsn=dsn,
        settings=DeepSeekSettings(api_key="key", model="deepseek-chat"),
        client=fake_s3,
    )

    assert outcome is Outcome.DONE
    assert calls == []
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.error_code == "attachment_unreadable"
