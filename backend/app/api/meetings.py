"""
Meetings API - Endpoints for meeting management, transcripts, and summaries.
"""
import time
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.services.meeting_transcript_service import meeting_transcript_service
from app.services.zoom_service import zoom_service
from app.services.task_approval_service import task_approval_service

router = APIRouter(prefix='/meetings', tags=['meetings'])


# ==========================================
# RESPONSE MODELS
# ==========================================

class MeetingItem(BaseModel):
    meetingId: str
    zoomMeetingId: str | None = None
    topic: str | None = None
    title: str | None = None
    teamId: str | None = None
    orgId: str
    status: str | None = None
    startTime: str | None = None
    startedAt: str | None = None
    endedAt: str | None = None
    durationMinutes: int | None = None
    joinUrl: str | None = None
    startUrl: str | None = None
    createdBy: str | None = None
    createdAt: str | None = None
    hasSummary: bool = False


class TranscriptSegment(BaseModel):
    text: str
    timestamp: int
    speaker: str | None = None


class TranscriptResponse(BaseModel):
    meetingId: str
    segments: List[TranscriptSegment]


class SummaryResponse(BaseModel):
    meetingId: str
    generated: bool = False
    title: str | None = None
    summary: str | None = None
    keyDecisions: List[str] | None = None
    actionItems: List[str] | None = None
    participants: List[str] | None = None
    topics: List[str] | None = None
    blockers: List[str] | None = None
    nextSteps: List[str] | None = None


class StartMeetingRequest(BaseModel):
    teamId: str | None = None
    title: str | None = None
    meetingUrl: str | None = None


class StartMeetingResponse(BaseModel):
    meetingId: str
    status: str


class EndMeetingRequest(BaseModel):
    generateSummary: bool = True


class EndMeetingResponse(BaseModel):
    meetingId: str
    status: str
    summaryGenerated: bool = False


class DeleteMeetingResponse(BaseModel):
    meetingId: str
    deleted: bool = True


class AppendTranscriptRequest(BaseModel):
    text: str
    timestamp: int
    speaker: str | None = None


class AppendTranscriptResponse(BaseModel):
    success: bool
    segmentCount: int = 0


class DetectedTaskItem(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    assignee: str | None = Field(default=None, max_length=320)
    priority: Literal['low', 'medium', 'high'] = 'medium'
    deadline: str | None = Field(default=None, max_length=320)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SubmitTasksRequest(BaseModel):
    tasks: List[DetectedTaskItem] = Field(..., min_length=1)
    summary: str | None = None


class SubmitTasksResponse(BaseModel):
    sent: bool
    pendingId: str | None = None
    managersNotified: int = 0
    message: str | None = None

# ==========================================
# MEETING LIFECYCLE ENDPOINTS
# ==========================================

@router.post('/start', response_model=StartMeetingResponse)
async def start_meeting(
    request: StartMeetingRequest,
    current_user: dict = Depends(get_current_user),
):
    """Start a new meeting and initialize transcript storage."""
    # Get user's org from their membership
    org_id = await _get_user_org_id(current_user)
    
    result = await meeting_transcript_service.start_meeting(
        org_id=org_id,
        team_id=request.teamId,
        created_by=current_user.get('uid'),
        title=request.title,
        meeting_url=request.meetingUrl,
    )
    return result


@router.post('/{meeting_id}/end', response_model=EndMeetingResponse)
async def end_meeting(
    meeting_id: str,
    request: EndMeetingRequest = EndMeetingRequest(),
    current_user: dict = Depends(get_current_user),
):
    """End a meeting and optionally generate summary."""
    org_id = await _get_user_org_id(current_user)
    
    result = await meeting_transcript_service.end_meeting(
        meeting_id=meeting_id,
        user_id=current_user.get('uid'),
        org_id=org_id,
        generate_summary=request.generateSummary,
    )
    return result


@router.delete('/{meeting_id}', response_model=DeleteMeetingResponse)
async def delete_meeting(
    meeting_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a meeting and all of its stored artifacts (admin only)."""
    membership = await _get_org_membership(current_user)
    if membership.get('role') != 'ORG_ADMIN':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only organization admins can delete meetings')

    result = await meeting_transcript_service.delete_meeting(
        meeting_id=meeting_id,
        org_id=membership['orgId'],
    )
    return result


# ==========================================
# TRANSCRIPT ENDPOINTS
# ==========================================

@router.post('/{meeting_id}/transcript', response_model=AppendTranscriptResponse)
async def append_transcript(
    meeting_id: str,
    request: AppendTranscriptRequest,
    current_user: dict = Depends(get_current_user),
):
    """Append a transcript segment to the meeting."""
    org_id = await _get_user_org_id(current_user)
    
    result = await meeting_transcript_service.append_transcript(
        meeting_id=meeting_id,
        text=request.text,
        timestamp=request.timestamp,
        speaker=request.speaker,
        org_id=org_id,
    )
    return result


@router.get('/{meeting_id}/transcript', response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get full transcript for a meeting."""
    org_id = await _get_user_org_id(current_user)
    
    result = await meeting_transcript_service.get_transcript(
        meeting_id=meeting_id,
        user_id=current_user.get('uid'),
        org_id=org_id,
    )
    return result


# ==========================================
# TASK DETECTION ENDPOINTS
# ==========================================

@router.post('/{meeting_id}/tasks', response_model=SubmitTasksResponse)
async def submit_detected_tasks(
    meeting_id: str,
    request: SubmitTasksRequest,
    current_user: dict = Depends(get_current_user),
):
    """Submit detected tasks for approval. Emits TASK_DETECTED to managers."""
    member_data = await _get_org_membership(current_user)
    org_id = member_data.get('orgId')
    
    # Get meeting to find the team
    meeting_data = await meeting_transcript_service.get_meeting(
        meeting_id=meeting_id,
        user_id=current_user.get('uid'),
        org_id=org_id,
    )
    
    if not meeting_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    team_id = meeting_data.get('teamId')
    
    # Normalize tasks
    normalized_tasks = []
    now_ms = int(time.time() * 1000)
    
    for task in request.tasks:
        title = (task.title or '').strip()
        if not title:
            continue
            
        normalized_tasks.append({
            'title': title,
            'description': (task.description or '').strip(),
            'assignee': (task.assignee or '').strip(),
            'priority': (task.priority or 'medium').lower(),
            'deadline': task.deadline,
            'confidence': task.confidence,
            'detectedAt': now_ms,
        })
    
    if not normalized_tasks:
        return SubmitTasksResponse(
            sent=False,
            message="No valid tasks provided"
        )
    
    # Emit to managers via WebSocket
    result = await task_approval_service.emit_task_detected(
        meeting_id=meeting_id,
        team_id=team_id,
        org_id=org_id,
        task_candidates=normalized_tasks,
    )
    
    return SubmitTasksResponse(
        sent=result.get('sent', False),
        pendingId=result.get('pendingId'),
        managersNotified=result.get('managersNotified', 0),
        message=f"Tasks submitted. {result.get('managersNotified', 0)} managers notified."
    )


# ==========================================
# SUMMARY ENDPOINTS
# ==========================================

@router.get('/{meeting_id}/summary', response_model=SummaryResponse)
async def get_summary(
    meeting_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get meeting summary (AI-generated)."""
    org_id = await _get_user_org_id(current_user)
    
    result = await meeting_transcript_service.get_summary(
        meeting_id=meeting_id,
        user_id=current_user.get('uid'),
        org_id=org_id,
    )
    return result


# ==========================================
# MEETING LISTING ENDPOINTS
# ==========================================

@router.get('', response_model=List[MeetingItem])
async def list_meetings(
    team_id: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """List meetings for user's teams."""
    org_id = await _get_user_org_id(current_user)
    
    # Try to get meetings from transcript service first
    meetings = await meeting_transcript_service.list_meetings(
        user_id=current_user.get('uid'),
        org_id=org_id,
        team_id=team_id,
        limit=limit,
    )
    
    # Also include Zoom meetings for backward compatibility
    try:
        zoom_meetings = zoom_service.list_meetings_for_user(current_user.get('uid'))
        
        # Merge, avoiding duplicates by meetingId
        existing_ids = {m.get('meetingId') for m in meetings}
        for zm in zoom_meetings:
            if zm.get('meetingId') not in existing_ids:
                meetings.append(zm)
    except Exception:
        pass  # Zoom service may not be configured
    
    return meetings


@router.get('/{meeting_id}', response_model=MeetingItem)
async def get_meeting(
    meeting_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get meeting metadata."""
    org_id = await _get_user_org_id(current_user)
    
    result = await meeting_transcript_service.get_meeting(
        meeting_id=meeting_id,
        user_id=current_user.get('uid'),
        org_id=org_id,
    )
    return result


# ==========================================
# HELPERS
# ==========================================

async def _get_user_org_id(current_user: dict) -> str:
    """Get the organization ID for the current user."""
    member_data = await _get_org_membership(current_user)
    return member_data['orgId']


async def _get_org_membership(current_user: dict) -> dict:
    """Fetch the org membership document for the current user."""
    from firebase_admin import firestore
    from app.core.security import ensure_firebase_initialized
    
    ensure_firebase_initialized()
    client = firestore.client()
    
    uid = current_user.get('uid')
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    
    # Query org_members to find user's organization
    docs = list(client.collection('org_members').where('uid', '==', uid).limit(1).stream())
    if not docs:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not part of any organization"
        )
    
    member_data = docs[0].to_dict() or {}
    org_id = member_data.get('orgId')
    
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization membership is invalid"
        )
    
    return member_data