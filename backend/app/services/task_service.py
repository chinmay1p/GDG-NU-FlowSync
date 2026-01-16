import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized
from app.utils.github import create_issue

logger = logging.getLogger(__name__)

PRIORITY_CHOICES = {'low', 'medium', 'high'}
DEFAULT_PRIORITY = 'medium'
DEFAULT_GITHUB_REPO = os.getenv('DEFAULT_GITHUB_REPO') or 'chinmay1p/GDG-NU-2026'


@dataclass
class SlackCommandPayload:
	team_id: str
	text: str
	slack_user_id: str
	user_name: str
	user_email: Optional[str] = None


@dataclass
class TaskFilters:
	assigned_to_email: Optional[str] = None
	priority: Optional[str] = None
	source: Optional[str] = None
	has_github_issue: Optional[bool] = None
	status: Optional[str] = None
	mine: bool = False


class TaskService:
	"""Task lifecycle service that connects Slack commands, manual creation, and GitHub issues."""

	TASKS_COLLECTION = 'tasks'
	ORG_INTEGRATIONS_COLLECTION = 'org_integrations'
	ORG_MEMBERS_COLLECTION = 'org_members'
	TEAM_MEMBERS_COLLECTION = 'team_members'

	def __init__(self) -> None:
		ensure_firebase_initialized()

	def create_task_from_slack(self, command: SlackCommandPayload) -> Dict:
		return self._create_task_from_slack_sync(command)

	async def create_task_manual(
	 self,
	 *,
	 creator_uid: str,
	 creator_email: str,
	 payload: Dict,
	) -> Dict:
		return await asyncio.to_thread(
		 self._create_task_manual_sync,
		 creator_uid,
		 creator_email,
		 payload,
		)

	async def list_tasks(self, *, current_user: Dict, filters: TaskFilters) -> List[Dict]:
		return await asyncio.to_thread(self._list_tasks_sync, current_user, filters)

	async def complete_task(self, *, current_user: Dict, task_id: str) -> Dict:
		return await asyncio.to_thread(self._complete_task_sync, current_user, task_id)

	def _create_task_from_slack_sync(self, command: SlackCommandPayload) -> Dict:
		client = self._get_client()
		parsed = self._parse_slack_command(command.text)
		creator_email = (command.user_email or '').strip().lower()
		if not creator_email:
			creator_email = f"slack:{(command.slack_user_id or 'unknown').strip()}"

		assignee_member = self._find_member_by_email(client, parsed['email'])
		if not assignee_member:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Assignee email was not found in StrataGem')

		org_id = assignee_member.get('orgId')
		if not org_id:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Assignee is missing workspace context')

		self._merge_org_integration(
		 client,
		 org_id,
		 {
		  'slack': {
		   'teamId': command.team_id,
		   'lastCommandAt': firestore.SERVER_TIMESTAMP,
		  },
		 },
		)

		return self._create_task_sync(
		 client=client,
		 org_id=org_id,
		 title=parsed['title'],
		 description=parsed['description'],
		 assigned_member=assignee_member,
		 priority=parsed['priority'],
		 source='SLACK',
		 created_by_email=creator_email,
		 status_value='APPROVED',
		 due_date=None,
		 create_github_issue=True,
		)

	def _create_task_manual_sync(self, creator_uid: str, creator_email: str, payload: Dict) -> Dict:
		client = self._get_client()
		creator_membership = self._find_member_by_uid(client, creator_uid)
		if not creator_membership:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You do not belong to any organization')

		org_id = creator_membership.get('orgId')
		self._ensure_manager(client, org_id, creator_uid)

		assigned_email = (payload.get('assignedToEmail') or '').strip().lower()
		if not assigned_email:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='assignedToEmail is required')

		assignee_member = self._find_org_member_by_email(client, org_id, assigned_email)
		if not assignee_member:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Assignee is not part of this organization')

		title = (payload.get('title') or '').strip()
		description = (payload.get('description') or '').strip()
		priority = (payload.get('priority') or DEFAULT_PRIORITY).lower()
		if priority not in PRIORITY_CHOICES:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Priority must be low, medium, or high')

		if not title or not description:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Title and description are required')

		due_date_value = payload.get('dueDate')
		due_date = None
		if due_date_value:
			due_date = self._parse_due_date(due_date_value)

		create_github_issue = bool(payload.get('createGithubIssue'))
		target_repo_id = payload.get('targetGithubRepoId')                           

		return self._create_task_sync(
		 client=client,
		 org_id=org_id,
		 title=title,
		 description=description,
		 assigned_member=assignee_member,
		 priority=priority,
		 source='DASHBOARD',
		 created_by_email=creator_email,
		 status_value='APPROVED',
		 due_date=due_date,
		 create_github_issue=create_github_issue,
		 target_repo_id=target_repo_id,
		)

	def _list_tasks_sync(self, current_user: Dict, filters: TaskFilters) -> List[Dict]:
		client = self._get_client()
		membership = self._find_member_by_uid(client, current_user.get('uid'))
		if not membership:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User is not part of an organization')

		org_id = membership.get('orgId')
		user_email = (current_user.get('email') or '').lower()
		role_value = (membership.get('role') or '').upper()
		is_manager = role_value == 'ORG_ADMIN' or self._has_manager_privileges(client, org_id, membership.get('uid'))

		query = client.collection(self.TASKS_COLLECTION).where('orgId', '==', org_id)

		entries: list[tuple[str, dict]] = []
		for doc in query.stream():
			data = doc.to_dict() or {}
			assignee_email = (data.get('assignedToEmail') or '').lower()

			if not is_manager and assignee_email != user_email:
				continue

			if filters.mine and assignee_email != user_email:
				continue

			if filters.assigned_to_email and assignee_email != filters.assigned_to_email.lower():
				continue

			if filters.priority and (data.get('priority') or '').lower() != filters.priority:
				continue

			if filters.source and (data.get('source') or '').upper() != filters.source.upper():
				continue

			if filters.has_github_issue is not None:
				has_issue = bool(data.get('githubIssueUrl'))
				if has_issue != filters.has_github_issue:
					continue

			if filters.status:
				status_value = (data.get('status') or '').upper()
				if status_value != filters.status.upper():
					continue

			entries.append((doc.id, data))

		def sort_key(entry: tuple[str, dict]):
			value = entry[1].get('createdAt')
			if isinstance(value, datetime):
				return value
			return datetime.min.replace(tzinfo=timezone.utc)

		entries.sort(key=sort_key, reverse=True)
		return [self._serialize_task(doc_id, data) for doc_id, data in entries]

	def _complete_task_sync(self, current_user: Dict, task_id: str) -> Dict:
		client = self._get_client()
		membership = self._find_member_by_uid(client, current_user.get('uid'))
		if not membership:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You are not part of any organization')

		if not task_id:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='taskId is required')

		doc_ref = client.collection(self.TASKS_COLLECTION).document(task_id)
		doc_snapshot = doc_ref.get()
		if not doc_snapshot.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Task not found')

		data = doc_snapshot.to_dict() or {}
		org_id = membership.get('orgId')
		if not org_id or data.get('orgId') != org_id:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You cannot modify this task')

		user_email = (current_user.get('email') or '').lower()
		assignee_email = (data.get('assignedToEmail') or '').lower()
		is_assignee = user_email and assignee_email == user_email
		is_manager = self._has_manager_privileges(client, org_id, membership.get('uid'))
		if not (is_assignee or is_manager):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only the assignee or managers can complete tasks')

		if (data.get('status') or '').upper() == 'COMPLETED':
			return self._serialize_task(task_id, data)

		completed_ts = datetime.now(timezone.utc)
		update_payload = {
		 'status': 'COMPLETED',
		 'completedAt': firestore.SERVER_TIMESTAMP,
		 'completedByEmail': user_email,
		}
		doc_ref.update(update_payload)
		data.update(
		 {
		  'status': 'COMPLETED',
		  'completedAt': completed_ts,
		  'completedByEmail': user_email,
		 }
		)
		return self._serialize_task(task_id, data)

	def _create_task_sync(
	 self,
	 *,
	 client,
	 org_id: str,
	 title: str,
	 description: str,
	 assigned_member: Dict,
	 priority: str,
	 source: str,
	 created_by_email: str,
	 status_value: str,
	 due_date: Optional[datetime],
	 create_github_issue: bool,
	 target_repo_id: Optional[str] = None,
	) -> Dict:
		task_ref = client.collection(self.TASKS_COLLECTION).document()
		payload = {
		 'taskId': task_ref.id,
		 'orgId': org_id,
		 'title': title,
		 'description': description,
		 'assignedToEmail': assigned_member.get('email') or '',
		 'assignedUid': assigned_member.get('uid'),
		 'priority': priority,
		 'status': status_value,
		 'source': source.upper(),
		 'createdAt': firestore.SERVER_TIMESTAMP,
		 'createdByEmail': created_by_email,
		 'dueDate': due_date,
		}
  
                                    
		if target_repo_id:
			payload['githubRepoId'] = target_repo_id
  
		task_ref.set(payload)

		issue_url = None
		issue_number = None
		if create_github_issue:
			issue_data = self._maybe_create_github_issue(
			 client, org_id, title, description, assigned_member.get('email'), target_repo_id
			)
			if issue_data:
				issue_url = issue_data.get('url')
				issue_number = issue_data.get('number')
				updates = {}
				if issue_url:
					updates['githubIssueUrl'] = issue_url
					payload['githubIssueUrl'] = issue_url
				if issue_number is not None:
					updates['githubIssueNumber'] = issue_number
					payload['githubIssueNumber'] = issue_number
				if updates:
					task_ref.update(updates)

		return self._serialize_task(task_ref.id, payload)

	def _maybe_create_github_issue(
	 self, 
	 client, 
	 org_id: str, 
	 title: str, 
	 description: str, 
	 assignee_email: Optional[str],
	 target_repo_id: Optional[str] = None
	) -> Optional[Dict]:
		"""
		Create a GitHub issue in the specified repository.
		
		Args:
			target_repo_id: Optional repository ID. If not provided, uses the default repo.
		"""
		integrations = self._get_org_integrations(client, org_id)
		github_config = integrations.get('github') or {}
  
                                        
		repositories = github_config.get('repositories')
		if repositories and isinstance(repositories, list):
                      
			target_repo = None
   
			if target_repo_id:
                              
				for repo_entry in repositories:
					if repo_entry.get('id') == target_repo_id:
						target_repo = repo_entry
						break
    
				if not target_repo:
					logger.warning('Target repo %s not found for org %s', target_repo_id, org_id)
					return None
			else:
                      
				for repo_entry in repositories:
					if repo_entry.get('isDefault'):
						target_repo = repo_entry
						break
    
                                   
				if not target_repo and len(repositories) > 0:
					target_repo = repositories[0]
   
			if not target_repo:
				logger.warning('No GitHub repos configured for org %s', org_id)
				return None
   
			repo = target_repo.get('repo')
			org_token = target_repo.get('token')
		else:
                                                       
			repo = github_config.get('repo')
   
                                                
			if not repo and DEFAULT_GITHUB_REPO:
				repo = DEFAULT_GITHUB_REPO
				self._merge_org_integration(client, org_id, {'github': {'repo': repo}})

			if not repo:
				logger.warning('No GitHub repo configured for org %s', org_id)
				return None
   
			org_token = github_config.get('token')

		body = 'Created from StrataGem\n'
		body += f"Assigned to: {assignee_email or 'Unassigned'}\n\n"
		body += description or 'No description provided.'

                                                                       
		return create_issue(repo, title or 'Meeting task', body, token=org_token)

	def _serialize_task(self, task_id: str, data: Dict) -> Dict:
		item = {**data}
		item['taskId'] = task_id
		item['priority'] = (item.get('priority') or DEFAULT_PRIORITY).lower()
		item['source'] = (item.get('source') or 'DASHBOARD').upper()
		item['status'] = (item.get('status') or 'APPROVED').upper()
		item['createdAt'] = self._format_timestamp(item.get('createdAt'))
		item['dueDate'] = self._format_timestamp(item.get('dueDate'))
		item['completedAt'] = self._format_timestamp(item.get('completedAt'))
		item['completedByEmail'] = (item.get('completedByEmail') or '').lower() or None
		item['githubIssueNumber'] = item.get('githubIssueNumber')
		return item

	@staticmethod
	def _format_timestamp(value):
		if isinstance(value, datetime):
			if value.tzinfo is None:
				value = value.replace(tzinfo=timezone.utc)
			return value.isoformat()
		return None

	def _parse_due_date(self, value) -> datetime:
		if isinstance(value, datetime):
			parsed = value
		else:
			try:
				parsed = datetime.fromisoformat(str(value))
			except ValueError:
				raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid dueDate format. Use ISO 8601.')
		if parsed.tzinfo is None:
			parsed = parsed.replace(tzinfo=timezone.utc)
		return parsed

	def _parse_slack_command(self, text: str) -> Dict:
		value = (text or '').strip()
		if not value:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Usage: /assign email task description priority=high')

		parts = value.split()
		if len(parts) < 2:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Please include an email and description')

		email = parts[0].lower()
		if '@' not in email:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='First argument must be an email address')

		priority = DEFAULT_PRIORITY
		description_tokens = []
		for token in parts[1:]:
			match = re.match(r'priority=(?P<value>\w+)', token, re.IGNORECASE)
			if match:
				choice = match.group('value').lower()
				if choice in PRIORITY_CHOICES:
					priority = choice
				continue
			description_tokens.append(token)

		description = ' '.join(description_tokens).strip()
		if not description:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Task description is required')

		title = description.split('\n', 1)[0]
		if len(title) > 80:
			title = title[:80].rstrip() + '…'

		return {'email': email, 'description': description, 'priority': priority, 'title': title or 'Slack task'}

	def _find_member_by_email(self, client, email: str) -> Optional[Dict]:
		value = (email or '').lower()
		if not value:
			return None
		query = (
		 client.collection(self.ORG_MEMBERS_COLLECTION)
		 .where('email', '==', value)
		 .limit(1)
		)
		matches = list(query.stream())
		if not matches:
			return None
		doc = matches[0]
		member = doc.to_dict() or {}
		if 'orgId' not in member:
			potential_org = None
			if '_' in doc.id:
				potential_org = doc.id.split('_', 1)[0]
			if potential_org:
				member['orgId'] = potential_org
		return member

	def _find_org_member_by_email(self, client, org_id: str, email: str) -> Optional[Dict]:
		query = (
		 client.collection(self.ORG_MEMBERS_COLLECTION)
		 .where('orgId', '==', org_id)
		 .where('email', '==', email.lower())
		 .limit(1)
		)
		matches = list(query.stream())
		if not matches:
			return None
		member = matches[0].to_dict() or {}
		member.setdefault('orgId', org_id)
		return member

	def _find_member_by_uid(self, client, uid: Optional[str]) -> Optional[Dict]:
		if not uid:
			return None
		query = (
		 client.collection(self.ORG_MEMBERS_COLLECTION)
		 .where('uid', '==', uid)
		 .limit(1)
		)
		matches = list(query.stream())
		if not matches:
			return None
		doc = matches[0]
		member = doc.to_dict() or {}
		if 'orgId' not in member and '_' in doc.id:
			member['orgId'] = doc.id.split('_', 1)[0]
		return member

	def _has_manager_privileges(self, client, org_id: str, uid: Optional[str]) -> bool:
		try:
			self._ensure_manager(client, org_id, uid)
			return True
		except HTTPException:
			return False

	def _ensure_manager(self, client, org_id: str, uid: Optional[str]) -> None:
		if not uid:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Manager privileges required')

		member_doc = client.collection(self.ORG_MEMBERS_COLLECTION).document(f'{org_id}_{uid}').get()
		if member_doc.exists:
			member_data = member_doc.to_dict() or {}
			if member_data.get('role') == 'ORG_ADMIN':
				return

		team_query = (
		 client.collection(self.TEAM_MEMBERS_COLLECTION)
		 .where('orgId', '==', org_id)
		 .where('uid', '==', uid)
		 .where('role', '==', 'MANAGER')
		 .limit(1)
		)
		if list(team_query.stream()):
			return

		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Manager privileges required')

	def _get_org_integrations(self, client, org_id: str) -> Dict:
		if not org_id:
			return {}
		doc = client.collection(self.ORG_INTEGRATIONS_COLLECTION).document(org_id).get()
		data = doc.to_dict() or {}
		if data and 'orgId' not in data:
			data['orgId'] = org_id
		return data

	def _merge_org_integration(self, client, org_id: str, updates: Dict) -> None:
		if not org_id:
			return
		ref = client.collection(self.ORG_INTEGRATIONS_COLLECTION).document(org_id)
		ref.set(updates, merge=True)

	@staticmethod
	def _get_client():
		ensure_firebase_initialized()
		return firestore.client()


default_task_service = TaskService()
task_service = default_task_service
