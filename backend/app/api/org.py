from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List
import re
import uuid
from datetime import datetime, timezone

from app.core.security import get_current_user
from app.services.org_service import org_service
from firebase_admin import firestore

router = APIRouter(prefix='/org', tags=['organizations'])


def _parse_github_repo(repo_input: str) -> str:
	"""
	Parse GitHub repository from various formats:
	- owner/repo
	- https://github.com/owner/repo
	- https://github.com/owner/repo.git
	- git@github.com:owner/repo.git
	
	Returns: owner/repo format
	"""
	repo = repo_input.strip()
 
                                
	if repo.endswith('.git'):
		repo = repo[:-4]
 
                                                  
	https_match = re.match(r'https?://github\.com/([^/]+)/([^/]+)', repo)
	if https_match:
		owner, repo_name = https_match.groups()
		return f"{owner}/{repo_name}"
 
                                            
	ssh_match = re.match(r'git@github\.com:([^/]+)/(.+)', repo)
	if ssh_match:
		owner, repo_name = ssh_match.groups()
		return f"{owner}/{repo_name}"
 
                                    
	if '/' in repo and repo.count('/') == 1:
		parts = repo.split('/')
		if parts[0] and parts[1]:
			return repo
 
	raise HTTPException(
	 status_code=status.HTTP_400_BAD_REQUEST,
	 detail='Invalid GitHub repo. Use: owner/repo or paste GitHub URL'
	)


def _migrate_to_multi_repo(client, org_id: str, github_data: dict) -> dict:
	"""
	Migrate old single-repo format to new multi-repo format.
	Old format: {'repo': 'owner/repo', 'token': 'xxx'}
	New format: {'repositories': [{'id': 'uuid', 'name': 'Repo', 'repo': 'owner/repo', ...}]}
	"""
                                 
	if 'repositories' in github_data and isinstance(github_data['repositories'], list):
		return github_data
 
                                   
	if 'repo' in github_data:
		repo_id = str(uuid.uuid4())
		repo_value = github_data['repo']
		token = github_data.get('token')
  
		new_repo = {
		 'id': repo_id,
		 'name': repo_value.split('/')[-1].title() if '/' in repo_value else 'Main Repository',
		 'repo': repo_value,
		 'isDefault': True,
		 'addedAt': datetime.now(timezone.utc).isoformat(),
		 'addedBy': github_data.get('updatedBy', 'system')
		}
  
		if token:
			new_repo['token'] = token
  
		new_format = {
		 'repositories': [new_repo]
		}
  
                                   
		integrations_ref = client.collection('org_integrations').document(org_id)
		integrations_ref.set({'github': new_format}, merge=True)
  
		return new_format
 
                      
	return {'repositories': []}


class CreateOrgRequest(BaseModel):
	name: str = Field(..., min_length=2, max_length=120)
	description: str | None = Field(default='', max_length=500)


class CreateOrgResponse(BaseModel):
	orgId: str
	joinCode: str


class JoinOrgRequest(BaseModel):
	joinCode: str = Field(..., min_length=6, max_length=6)


class JoinOrgResponse(BaseModel):
	orgId: str
	role: str


class UpdateGitHubIntegrationRequest(BaseModel):
	githubRepo: str = Field(..., min_length=3, max_length=200, description="GitHub repo in format: owner/repo")
	githubToken: Optional[str] = Field(None, max_length=500, description="Optional: Personal Access Token for private repos")


class AddGitHubRepoRequest(BaseModel):
	name: str = Field(..., min_length=2, max_length=100, description="Display name for the repository")
	githubRepo: str = Field(..., min_length=3, max_length=200, description="GitHub repo in format: owner/repo")
	githubToken: Optional[str] = Field(None, max_length=500, description="Optional: Personal Access Token for private repos")
	isDefault: bool = Field(default=False, description="Set as default repository")


class SetDefaultRepoRequest(BaseModel):
	repoId: str = Field(..., description="Repository ID to set as default")


class IntegrationsResponse(BaseModel):
	orgId: str
	github: Optional[dict] = None
	slack: Optional[dict] = None


@router.post('/create', response_model=CreateOrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(request: CreateOrgRequest, current_user: dict = Depends(get_current_user)):
	name = request.name.strip()
	if not name:
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Organization name is required')

	description = (request.description or '').strip()

	result = await org_service.create_organization(
	 uid=current_user.get('uid'),
	 email=current_user.get('email'),
	 name=name,
	 description=description,
	)
	return CreateOrgResponse(**result)


@router.post('/join', response_model=JoinOrgResponse)
async def join_org(request: JoinOrgRequest, current_user: dict = Depends(get_current_user)):
	join_code = request.joinCode.strip()
	if len(join_code) != 6 or not join_code.isdigit():
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Enter a valid 6-digit join code')

	result = await org_service.join_organization(
	 uid=current_user.get('uid'),
	 email=current_user.get('email'),
	 join_code=join_code,
	)
	return JoinOrgResponse(**result)


@router.get('/integrations', response_model=IntegrationsResponse)
async def get_integrations(current_user: dict = Depends(get_current_user)):
	"""Get organization integrations (GitHub, Slack, etc.) - Auto-migrates to multi-repo format"""
	uid = current_user.get('uid')
	if not uid:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
 
                            
	client = firestore.client()
	member_query = client.collection('org_members').where('uid', '==', uid).limit(1)
	members = list(member_query.stream())
 
	if not members:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='You are not part of any organization')
 
	member_data = members[0].to_dict() or {}
	org_id = member_data.get('orgId')
 
	if not org_id:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Organization ID not found')
 
                       
	integrations_doc = client.collection('org_integrations').document(org_id).get()
	integrations_data = integrations_doc.to_dict() or {}
 
                                                                 
	github_data = integrations_data.get('github')
	if github_data:
		github_data = _migrate_to_multi_repo(client, org_id, github_data)
 
	return IntegrationsResponse(
	 orgId=org_id,
	 github=github_data,
	 slack=integrations_data.get('slack')
	)


@router.put('/integrations/github')
async def update_github_integration(
 request: UpdateGitHubIntegrationRequest,
 current_user: dict = Depends(get_current_user)
):
	"""Update GitHub integration for organization (Admin only)"""
	uid = current_user.get('uid')
	if not uid:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
 
                                                                           
	repo = _parse_github_repo(request.githubRepo)
 
                                                        
	client = firestore.client()
	member_query = client.collection('org_members').where('uid', '==', uid).limit(1)
	members = list(member_query.stream())
 
	if not members:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='You are not part of any organization')
 
	member_data = members[0].to_dict() or {}
	org_id = member_data.get('orgId')
	role = member_data.get('role')
 
                         
	if role != 'ORG_ADMIN':
		raise HTTPException(
		 status_code=status.HTTP_403_FORBIDDEN,
		 detail='Only organization admins can update integrations'
		)
 
                          
	integration_data = {
	 'github': {
	  'repo': repo,
	  'updatedAt': datetime.now(timezone.utc).isoformat(),
	  'updatedBy': current_user.get('email')
	 }
	}
 
                                                           
	if request.githubToken:
		integration_data['github']['token'] = request.githubToken
 
	integrations_ref = client.collection('org_integrations').document(org_id)
	integrations_ref.set(integration_data, merge=True)
 
	return {
	 'success': True,
	 'message': 'GitHub integration updated successfully',
	 'repo': repo
	}


@router.post('/integrations/github/add')
async def add_github_repository(
 request: AddGitHubRepoRequest,
 current_user: dict = Depends(get_current_user)
):
	"""Add a new GitHub repository to the organization (Admin only)"""
	uid = current_user.get('uid')
	if not uid:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
 
                                 
	repo = _parse_github_repo(request.githubRepo)
 
                                                        
	client = firestore.client()
	member_query = client.collection('org_members').where('uid', '==', uid).limit(1)
	members = list(member_query.stream())
 
	if not members:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='You are not part of any organization')
 
	member_data = members[0].to_dict() or {}
	org_id = member_data.get('orgId')
	role = member_data.get('role')
 
                         
	if role != 'ORG_ADMIN':
		raise HTTPException(
		 status_code=status.HTTP_403_FORBIDDEN,
		 detail='Only organization admins can update integrations'
		)
 
                           
	integrations_ref = client.collection('org_integrations').document(org_id)
	integrations_doc = integrations_ref.get()
	integrations_data = integrations_doc.to_dict() or {}
	github_data = integrations_data.get('github', {})
 
                         
	github_data = _migrate_to_multi_repo(client, org_id, github_data)
 
	repositories = github_data.get('repositories', [])
 
                               
	for existing_repo in repositories:
		if existing_repo.get('repo') == repo:
			raise HTTPException(
			 status_code=status.HTTP_400_BAD_REQUEST,
			 detail='This repository is already added'
			)
 
                              
	repo_id = str(uuid.uuid4())
	new_repo = {
	 'id': repo_id,
	 'name': request.name.strip(),
	 'repo': repo,
	 'isDefault': request.isDefault,
	 'addedAt': datetime.now(timezone.utc).isoformat(),
	 'addedBy': current_user.get('email')
	}
 
	if request.githubToken:
		new_repo['token'] = request.githubToken
 
                                              
	if request.isDefault:
		for r in repositories:
			r['isDefault'] = False
                                             
	elif len(repositories) == 0:
		new_repo['isDefault'] = True
 
	repositories.append(new_repo)
 
                  
	integrations_ref.set({
	 'github': {
	  'repositories': repositories
	 }
	}, merge=True)
 
	return {
	 'success': True,
	 'message': 'Repository added successfully',
	 'repoId': repo_id,
	 'repo': new_repo
	}


@router.delete('/integrations/github/{repo_id}')
async def delete_github_repository(
 repo_id: str,
 current_user: dict = Depends(get_current_user)
):
	"""Delete a GitHub repository from the organization (Admin only)"""
	uid = current_user.get('uid')
	if not uid:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
 
                                                        
	client = firestore.client()
	member_query = client.collection('org_members').where('uid', '==', uid).limit(1)
	members = list(member_query.stream())
 
	if not members:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='You are not part of any organization')
 
	member_data = members[0].to_dict() or {}
	org_id = member_data.get('orgId')
	role = member_data.get('role')
 
                         
	if role != 'ORG_ADMIN':
		raise HTTPException(
		 status_code=status.HTTP_403_FORBIDDEN,
		 detail='Only organization admins can update integrations'
		)
 
                           
	integrations_ref = client.collection('org_integrations').document(org_id)
	integrations_doc = integrations_ref.get()
	integrations_data = integrations_doc.to_dict() or {}
	github_data = integrations_data.get('github', {})
 
                         
	github_data = _migrate_to_multi_repo(client, org_id, github_data)
 
	repositories = github_data.get('repositories', [])
 
                                 
	repo_to_delete = None
	new_repositories = []
	for repo in repositories:
		if repo.get('id') == repo_id:
			repo_to_delete = repo
		else:
			new_repositories.append(repo)
 
	if not repo_to_delete:
		raise HTTPException(
		 status_code=status.HTTP_404_NOT_FOUND,
		 detail='Repository not found'
		)
 
                                                                          
	if repo_to_delete.get('isDefault') and len(new_repositories) > 0:
		new_repositories[0]['isDefault'] = True
 
                  
	integrations_ref.set({
	 'github': {
	  'repositories': new_repositories
	 }
	}, merge=True)
 
	return {
	 'success': True,
	 'message': 'Repository deleted successfully'
	}


@router.put('/integrations/github/set-default')
async def set_default_github_repository(
 request: SetDefaultRepoRequest,
 current_user: dict = Depends(get_current_user)
):
	"""Set a repository as the default for the organization (Admin only)"""
	uid = current_user.get('uid')
	if not uid:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
 
                                                        
	client = firestore.client()
	member_query = client.collection('org_members').where('uid', '==', uid).limit(1)
	members = list(member_query.stream())
 
	if not members:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='You are not part of any organization')
 
	member_data = members[0].to_dict() or {}
	org_id = member_data.get('orgId')
	role = member_data.get('role')
 
                         
	if role != 'ORG_ADMIN':
		raise HTTPException(
		 status_code=status.HTTP_403_FORBIDDEN,
		 detail='Only organization admins can update integrations'
		)
 
                           
	integrations_ref = client.collection('org_integrations').document(org_id)
	integrations_doc = integrations_ref.get()
	integrations_data = integrations_doc.to_dict() or {}
	github_data = integrations_data.get('github', {})
 
                         
	github_data = _migrate_to_multi_repo(client, org_id, github_data)
 
	repositories = github_data.get('repositories', [])
 
                                         
	repo_found = False
	for repo in repositories:
		if repo.get('id') == request.repoId:
			repo['isDefault'] = True
			repo_found = True
		else:
			repo['isDefault'] = False
 
	if not repo_found:
		raise HTTPException(
		 status_code=status.HTTP_404_NOT_FOUND,
		 detail='Repository not found'
		)
 
                  
	integrations_ref.set({
	 'github': {
	  'repositories': repositories
	 }
	}, merge=True)
 
	return {
	 'success': True,
	 'message': 'Default repository updated successfully'
	}
