from fastapi import APIRouter, status

from app.errors import ChatError
from app.jobs import JobStore, submit_job, to_response
from app.schemas import ChatRequest, JobResponse

router = APIRouter()


@router.post(
    "/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
def create_job(request: ChatRequest) -> JobResponse:
    """Record a queued job and hand it to the Celery worker."""
    return submit_job(request.messages)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def read_job(job_id: str) -> JobResponse:
    """Current status of a job, plus the reply once the worker has finished."""
    job = JobStore().get(job_id)
    if job is None:
        raise ChatError("not_found")
    return to_response(job)
