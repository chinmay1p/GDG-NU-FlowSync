import logging
import time
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized, require_zoom_bot_key
from app.services.meeting_transcript_service import meeting_transcript_service
from app.services.task_approval_service import task_approval_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/zoom-ai', tags=['zoom-ai'])


class SegmentIngestRequest(BaseModel):
    orgId: str = Field(..., min_length=1)
    teamId: str | None = Field(default=None)
    text: str = Field(..., min_length=1, max_length=8000)
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    speaker: str | None = Field(default=None, max_length=120)


class MeetingCompleteRequest(BaseModel):
    orgId: str = Field(..., min_length=1)
    teamId: str | None = Field(default=None)
    generateSummary: bool = True


class DetectedTask(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    assignee: str | None = Field(default=None, max_length=320)
    assigneeEmail: str | None = Field(default=None, max_length=320)
    priority: Literal['low', 'medium', 'high'] | None = Field(default='medium')
    deadline: str | None = Field(default=None, max_length=320)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TaskDetectionRequest(BaseModel):
    orgId: str = Field(..., min_length=1)
    teamId: str | None = Field(default=None)
    tasks: List[DetectedTask] = Field(..., min_length=1)


@router.post('/meetings/{meeting_id}/segments', status_code=status.HTTP_202_ACCEPTED)
async def ingest_segment(
    meeting_id: str,
    payload: SegmentIngestRequest,
    _: str = Depends(require_zoom_bot_key),
):
    """Store a finalized transcript segment coming from the Zoom bot pipeline."""
    meeting_context = _ensure_meeting_record(meeting_id, payload.orgId, payload.teamId)
    result = await meeting_transcript_service.append_transcript(
        meeting_id=meeting_id,
        text=payload.text,
        timestamp=payload.timestamp,
        speaker=payload.speaker,
        org_id=payload.orgId,
        team_id=meeting_context.get('teamId'),
        allow_create=True,
        created_by='zoom-bot',
    )
    return result


@router.post('/meetings/{meeting_id}/complete')
async def mark_meeting_complete(
    meeting_id: str,
    payload: MeetingCompleteRequest,
    _: str = Depends(require_zoom_bot_key),
):
    """Mark a meeting as finished and trigger summary generation."""
    meeting_context = _ensure_meeting_record(meeting_id, payload.orgId, payload.teamId)
    result = await meeting_transcript_service.end_meeting(
        meeting_id=meeting_id,
        user_id='zoom-bot',
        org_id=meeting_context.get('orgId'),
        generate_summary=payload.generateSummary,
    )
    return result


@router.post('/meetings/{meeting_id}/tasks', status_code=status.HTTP_202_ACCEPTED)
async def ingest_detected_tasks(
    meeting_id: str,
    payload: TaskDetectionRequest,
    _: str = Depends(require_zoom_bot_key),
):
    """Persist detected tasks and fan-out approvals to managers via WebSocket."""
    meeting_context = _ensure_meeting_record(meeting_id, payload.orgId, payload.teamId)

    normalized_tasks: List[dict] = []
    now_ms = int(time.time() * 1000)

    for item in payload.tasks:
        title = (item.title or '').strip()
        description = (item.description or '').strip() if item.description else ''
        assignee_value = (item.assignee or item.assigneeEmail or '').strip()
        if not title:
            continue

        normalized_tasks.append(
            {
                'title': title,
                'description': description,
                'assignee': assignee_value,
                'priority': (item.priority or 'medium').lower(),
                'deadline': item.deadline,
                'confidence': item.confidence,
                'detectedAt': now_ms,
            }
        )

    if not normalized_tasks:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='No valid tasks supplied')

    result = await task_approval_service.emit_task_detected(
        meeting_id=meeting_id,
        team_id=meeting_context.get('teamId'),
        org_id=meeting_context.get('orgId'),
        task_candidates=normalized_tasks,
    )
    return result


def _ensure_meeting_record(meeting_id: str, org_id: str, team_id: Optional[str]) -> dict:
    """Ensure a meeting document exists so downstream services have context."""
    ensure_firebase_initialized()
    client = firestore.client()
    meeting_ref = client.collection(meeting_transcript_service.MEETINGS_COLLECTION).document(meeting_id)
    snapshot = meeting_ref.get()

    if snapshot.exists:
        data = snapshot.to_dict() or {}
        if data.get('orgId') != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Meeting belongs to another organization')
        if team_id and not data.get('teamId'):
            meeting_ref.update({'teamId': team_id})
            data['teamId'] = team_id
        return data

    payload = {
        'meetingId': meeting_id,
        'orgId': org_id,
        'teamId': team_id,
        'status': meeting_transcript_service.STATUS_ACTIVE,
        'createdBy': 'zoom-bot',
        'startedAt': firestore.SERVER_TIMESTAMP,
        'hasSummary': False,
    }
    meeting_ref.set(payload)
    logger.info('Created placeholder meeting %s for org %s via zoom-ai ingest', meeting_id, org_id)
    return payload
