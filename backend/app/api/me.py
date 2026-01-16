from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.services.context_service import context_service

router = APIRouter(prefix='/me', tags=['me'])


class TeamMember(BaseModel):
	uid: str | None = None
	email: str | None = None
	role: str | None = None


class OrganizationInfo(BaseModel):
	orgId: str
	name: str | None = None
	joinCode: str | None = None
	description: str | None = None


class OrgTeam(BaseModel):
	teamId: str
	teamName: str | None = None
	description: str | None = None
	members: list[TeamMember] = Field(default_factory=list)


class UserTeam(BaseModel):
	teamId: str
	teamName: str | None = None
	role: str
	members: list[TeamMember] = Field(default_factory=list)


class ContextResponse(BaseModel):
	uid: str
	email: str | None = None
	hasOrg: bool = True
	orgId: str | None = None
	orgRole: str | None = None
	organization: OrganizationInfo | None = None
	teams: list[UserTeam] = Field(default_factory=list)
	orgTeams: list[OrgTeam] = Field(default_factory=list)
	orgMembers: list[TeamMember] = Field(default_factory=list)


@router.get('/context', response_model=ContextResponse)
async def get_context(current_user: dict = Depends(get_current_user)):
	payload = await context_service.get_user_context(
	 uid=current_user.get('uid'),
	 email=current_user.get('email'),
	)
	return payload
