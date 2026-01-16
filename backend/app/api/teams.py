from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field, validator

from app.core.security import get_current_user
from app.services.team_service import team_service

router = APIRouter(prefix='/teams', tags=['teams'])


class TeamResponse(BaseModel):
	teamId: str
	orgId: str
	name: str
	description: str | None = None


class CreateTeamRequest(BaseModel):
	name: str = Field(..., min_length=2, max_length=120)
	description: str | None = Field(default='', max_length=500)


class UpdateTeamRequest(BaseModel):
	name: str = Field(..., min_length=2, max_length=120)
	description: str | None = Field(default='', max_length=500)


class TeamMemberRequest(BaseModel):
	userId: str = Field(..., min_length=1)
	role: str = Field(...)

	@validator('role')
	def validate_role(cls, value):                                    
		upper_value = (value or '').upper()
		if upper_value not in {'MANAGER', 'EMPLOYEE'}:
			raise ValueError('Role must be MANAGER or EMPLOYEE')
		return upper_value


class TeamMemberResponse(BaseModel):
	teamId: str
	teamName: str | None = None
	uid: str
	email: str | None = None
	role: str


@router.post('', response_model=TeamResponse, status_code=201)
async def create_team(request: CreateTeamRequest, current_user: dict = Depends(get_current_user)):
	return await team_service.create_team(
	 uid=current_user.get('uid'),
	 name=request.name,
	 description=request.description,
	)


@router.patch('/{team_id}', response_model=TeamResponse)
async def update_team(
 request: UpdateTeamRequest,
 team_id: str = Path(..., description='Team identifier'),
 current_user: dict = Depends(get_current_user),
):
	return await team_service.rename_team(
	 uid=current_user.get('uid'),
	 team_id=team_id,
	 name=request.name,
	 description=request.description,
	)


@router.delete('/{team_id}', response_model=dict)
async def delete_team(
 team_id: str = Path(..., description='Team identifier'),
 current_user: dict = Depends(get_current_user),
):
	return await team_service.delete_team(
	 uid=current_user.get('uid'),
	 team_id=team_id,
	)


@router.post('/{team_id}/members', response_model=TeamMemberResponse, status_code=201)
async def add_team_member(
 team_id: str,
 request: TeamMemberRequest,
 current_user: dict = Depends(get_current_user),
):
	return await team_service.add_member(
	 uid=current_user.get('uid'),
	 team_id=team_id,
	 target_uid=request.userId,
	 role=request.role,
	)


@router.patch('/{team_id}/members/{user_id}', response_model=TeamMemberResponse)
async def update_team_member(
 team_id: str,
 user_id: str,
 request: TeamMemberRequest,
 current_user: dict = Depends(get_current_user),
):
	return await team_service.update_member_role(
	 uid=current_user.get('uid'),
	 team_id=team_id,
	 target_uid=user_id,
	 role=request.role,
	)


@router.delete('/{team_id}/members/{user_id}', response_model=dict)
async def remove_team_member(team_id: str, user_id: str, current_user: dict = Depends(get_current_user)):
	return await team_service.remove_member(
	 uid=current_user.get('uid'),
	 team_id=team_id,
	 target_uid=user_id,
	)
