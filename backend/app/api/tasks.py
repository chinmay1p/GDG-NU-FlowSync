from datetime import datetime
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, Path, Query, status
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.services.task_service import TaskFilters, task_service
from app.services.task_approval_service import task_approval_service

router = APIRouter(prefix='/tasks', tags=['tasks'])

PriorityLiteral = Literal['low', 'medium', 'high']


class TaskCreateRequest(BaseModel):
	title: str = Field(..., min_length=3, max_length=160)
	description: str = Field(..., min_length=5, max_length=4000)
	assignedToEmail: str = Field(..., min_length=5, max_length=320)
	priority: PriorityLiteral = Field(default='medium')
	dueDate: datetime | None = None
	createGithubIssue: bool = False


class TaskResponse(BaseModel):
	taskId: str
	title: str
	description: str
	assignedToEmail: str | None = None
	assignedUid: str | None = None
	priority: str
	status: str
	source: str
	createdAt: str | None = None
	dueDate: str | None = None
	completedAt: str | None = None
	completedByEmail: str | None = None
	githubIssueUrl: str | None = None
	githubIssueNumber: int | None = None
	createdByEmail: str | None = None


                                            
                      
                                            

class TaskCandidateEdit(BaseModel):
	title: str | None = None
	description: str | None = None
	assignee: str | None = None
	priority: str | None = None
	deadline: str | None = None


class TaskApproveRequest(BaseModel):
	pendingId: str = Field(..., min_length=1)
	taskIndex: int = Field(..., ge=0)
	edits: TaskCandidateEdit | None = None
	createGithubIssue: bool = False


class TaskApproveResponse(BaseModel):
	taskId: str
	pendingId: str
	approved: bool


class TaskRejectRequest(BaseModel):
	pendingId: str = Field(..., min_length=1)
	taskIndex: int = Field(..., ge=0)
	reason: str | None = None


class TaskRejectResponse(BaseModel):
	pendingId: str
	taskIndex: int
	rejected: bool


class TaskBulkEditEntry(BaseModel):
	taskIndex: int = Field(..., ge=0)
	edits: TaskCandidateEdit | None = None


class TaskApproveBatchRequest(BaseModel):
	pendingId: str = Field(..., min_length=1)
	edits: List[TaskBulkEditEntry] | None = None
	createGithubIssue: bool = False


class TaskApproveBatchResponse(BaseModel):
	pendingId: str
	approvedTaskIds: List[str]
	remaining: int


class TaskRejectBatchRequest(BaseModel):
	pendingId: str = Field(..., min_length=1)
	taskIndexes: List[int] | None = None
	reason: str | None = None


class TaskRejectBatchResponse(BaseModel):
	pendingId: str
	rejectedCount: int
	remaining: int


class TaskCandidate(BaseModel):
	title: str | None = None
	description: str | None = None
	assignee: str | None = None
	priority: str | None = None
	deadline: str | None = None
	confidence: float | None = None
	approved: bool | None = None
	rejected: bool | None = None


class PendingApproval(BaseModel):
	pendingId: str
	meetingId: str | None = None
	teamId: str | None = None
	orgId: str
	taskCandidates: List[TaskCandidate]
	status: str
	createdAt: str | None = None


                                            
                         
                                            

@router.post('/create', response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(request: TaskCreateRequest, current_user: dict = Depends(get_current_user)):
	payload = {
	 'title': request.title.strip(),
	 'description': request.description.strip(),
	 'assignedToEmail': request.assignedToEmail.strip().lower(),
	 'priority': request.priority,
	 'dueDate': request.dueDate.isoformat() if isinstance(request.dueDate, datetime) else request.dueDate,
	 'createGithubIssue': request.createGithubIssue,
	}

	result = await task_service.create_task_manual(
	 creator_uid=current_user.get('uid'),
	 creator_email=current_user.get('email'),
	 payload=payload,
	)
	return TaskResponse(**result)


@router.get('', response_model=list[TaskResponse])
async def list_tasks(
 current_user: dict = Depends(get_current_user),
 assignedToEmail: str | None = Query(default=None),
 priority: PriorityLiteral | None = Query(default=None),
 source: str | None = Query(default=None),
 hasGithubIssue: bool | None = Query(default=None),
 mine: bool = Query(default=False),
 status: str | None = Query(default=None),
):
	filters = TaskFilters(
	 assigned_to_email=assignedToEmail.lower() if assignedToEmail else None,
	 priority=priority,
	 source=source,
	 has_github_issue=hasGithubIssue,
	 status=status.upper() if status else None,
	 mine=mine,
	)

	tasks = await task_service.list_tasks(current_user=current_user, filters=filters)
	return [TaskResponse(**task) for task in tasks]


@router.post('/{task_id}/complete', response_model=TaskResponse)
async def complete_task(
 task_id: str = Path(..., min_length=4, description='Task identifier'),
 current_user: dict = Depends(get_current_user),
):
	task = await task_service.complete_task(current_user=current_user, task_id=task_id)
	return TaskResponse(**task)


                                            
                         
                                            

@router.post('/approve', response_model=TaskApproveResponse)
async def approve_task(
 request: TaskApproveRequest,
 current_user: dict = Depends(get_current_user),
):
	"""
	Approve an AI-detected task candidate and create the actual task.
	Only managers can approve tasks.
	"""
	org_id = await _get_user_org_id(current_user)
 
	edits_dict = None
	if request.edits:
		edits_dict = {k: v for k, v in request.edits.model_dump().items() if v is not None}
 
	result = await task_approval_service.approve_task(
	 pending_id=request.pendingId,
	 task_index=request.taskIndex,
	 user_id=current_user.get('uid'),
	 user_email=current_user.get('email'),
	 edits=edits_dict,
	 create_github_issue=request.createGithubIssue,
	)
	return TaskApproveResponse(**result)


@router.post('/approve/batch', response_model=TaskApproveBatchResponse)
async def approve_tasks_batch(
 request: TaskApproveBatchRequest,
 current_user: dict = Depends(get_current_user),
):
	"""Approve all pending candidates (optionally with edits) in a single action."""
	edits_map: dict[int, dict] = {}
	if request.edits:
		for entry in request.edits:
			if entry.edits:
				edits_map[entry.taskIndex] = {
				 k: v
				 for k, v in entry.edits.model_dump().items()
				 if v is not None
				}

	result = await task_approval_service.approve_all_tasks(
	 pending_id=request.pendingId,
	 user_id=current_user.get('uid'),
	 user_email=current_user.get('email'),
	 edits_by_index=edits_map,
	 create_github_issue=request.createGithubIssue,
	)
	return TaskApproveBatchResponse(**result)


@router.post('/reject', response_model=TaskRejectResponse)
async def reject_task(
 request: TaskRejectRequest,
 current_user: dict = Depends(get_current_user),
):
	"""
	Reject an AI-detected task candidate (no DB write).
	Only managers can reject tasks.
	"""
	org_id = await _get_user_org_id(current_user)
 
	result = await task_approval_service.reject_task(
	 pending_id=request.pendingId,
	 task_index=request.taskIndex,
	 user_id=current_user.get('uid'),
	 reason=request.reason,
	)
	return TaskRejectResponse(**result)


@router.post('/reject/batch', response_model=TaskRejectBatchResponse)
async def reject_tasks_batch(
 request: TaskRejectBatchRequest,
 current_user: dict = Depends(get_current_user),
):
	"""Reject multiple pending candidates at once."""
	result = await task_approval_service.reject_all_tasks(
	 pending_id=request.pendingId,
	 user_id=current_user.get('uid'),
	 reason=request.reason,
	 task_indexes=request.taskIndexes,
	)
	return TaskRejectBatchResponse(**result)


@router.get('/pending', response_model=List[PendingApproval])
async def list_pending_approvals(
 current_user: dict = Depends(get_current_user),
):
	"""
	Get all pending task approvals for the current manager.
	"""
	org_id = await _get_user_org_id(current_user)
 
	result = await task_approval_service.get_pending_approvals(
	 user_id=current_user.get('uid'),
	 org_id=org_id,
	)
	return [PendingApproval(**p) for p in result]


                                            
         
                                            

async def _get_user_org_id(current_user: dict) -> str:
	"""Get the organization ID for the current user."""
	from firebase_admin import firestore
	from app.core.security import ensure_firebase_initialized
 
	ensure_firebase_initialized()
	client = firestore.client()
 
	uid = current_user.get('uid')
	if not uid:
		raise Exception("Invalid user")
 
	docs = list(client.collection('org_members').where('uid', '==', uid).limit(1).stream())
	if not docs:
		raise Exception("User is not part of any organization")
 
	member_data = docs[0].to_dict() or {}
	return member_data.get('orgId', '')