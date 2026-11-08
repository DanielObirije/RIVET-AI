from fastapi import APIRouter, status

from app.jobs import submit_job
from app.schemas import ChatRequest, JobResponse

router = APIRouter()


@router.post("/chat", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_chat(request: ChatRequest) -> JobResponse:
    """Accept a chat turn and return a job id; the worker generates the reply.

    Kept at the URL the web app already uses. It shares the same submission
    path as POST /api/jobs, so there is one way for a chat to reach the model.
    """
    return submit_job(request.messages)
