from fastapi import APIRouter, status

from app.errors import ChatError
from app.jobs import get_job, submit_job, submit_retry, to_response
from app.schemas import ChatRequest, JobResponse

router = APIRouter()


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(request: ChatRequest) -> JobResponse:
    """Record a queued job and publish its id to the SQS queue."""
    return submit_job(request.messages)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def read_job(job_id: str) -> JobResponse:
    """Current status of a job, plus the reply once the worker has finished."""
    job = get_job(job_id)
    if job is None:
        raise ChatError("not_found")
    return to_response(job)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_job(job_id: str) -> JobResponse:
    """Create a new job from a failed one; the original is never modified.

    Independent of the DLQ: the conversation is already in PostgreSQL, so a
    retry is a fresh row and a fresh message, not a replay of an old one.
    """
    return submit_retry(job_id)
