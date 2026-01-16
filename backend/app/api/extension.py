from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.services.extension_session_service import extension_session_service

router = APIRouter(prefix='/extension', tags=['extension'])


class SessionCreateRequest(BaseModel):
	orgId: str = Field(..., min_length=1)


class SessionCreateResponse(BaseModel):
	sessionId: str
	expiresAt: datetime


class SessionVerifyRequest(BaseModel):
	sessionId: str = Field(..., min_length=1)


class SessionVerifyResponse(BaseModel):
	uid: str
	email: str | None = None
	orgId: str


@router.post('/session/create', response_model=SessionCreateResponse)
async def create_session(payload: SessionCreateRequest, current_user: dict = Depends(get_current_user)):
	result = await extension_session_service.create_session(
	 uid=current_user.get('uid'),
	 email=current_user.get('email'),
	 org_id=payload.orgId,
	)
	return result


@router.post('/session/verify', response_model=SessionVerifyResponse)
async def verify_session(payload: SessionVerifyRequest):
	result = await extension_session_service.verify_session(payload.sessionId)
	return result
