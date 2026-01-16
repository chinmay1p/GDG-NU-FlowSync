import logging
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.services.zoom_service import zoom_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/zoom', tags=['zoom'])


class CreateZoomMeetingRequest(BaseModel):
	teamId: str = Field(..., min_length=4)
	topic: str = Field(..., min_length=3, max_length=200)
	startTime: str = Field(..., description='ISO 8601 start time (UTC recommended)')
	durationMinutes: int = Field(..., ge=1, le=600)


class ZoomMeetingResponse(BaseModel):
	meetingId: str
	zoomMeetingId: str | None = None
	joinUrl: str | None = None
	startUrl: str | None = None
	createdBy: str
	teamId: str
	orgId: str
	status: str
	topic: str | None = None
	startTime: str | None = None
	durationMinutes: int | None = None
	createdAt: str | None = None


@router.post('/meeting/create', response_model=ZoomMeetingResponse, status_code=status.HTTP_201_CREATED)
async def create_zoom_meeting(request: CreateZoomMeetingRequest, current_user: dict = Depends(get_current_user)):
	uid = current_user.get('uid') or 'unknown'
	logger.info('API: create_zoom_meeting uid=%s payload=%s', uid, request.dict())
	try:
		result = zoom_service.create_meeting(
		 uid=uid,
		 team_id=request.teamId,
		 topic=request.topic,
		 start_time=request.startTime,
		 duration_minutes=request.durationMinutes,
		)
		return ZoomMeetingResponse(**result)
	except Exception as exc:                                                            
		logger.exception('Failed to create Zoom meeting for uid=%s: %s', uid, getattr(exc, 'detail', str(exc)))
		raise


