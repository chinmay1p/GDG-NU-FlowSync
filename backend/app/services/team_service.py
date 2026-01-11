import asyncio
import logging
from typing import Dict

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class TeamService:

	VALID_TEAM_ROLES = {'MANAGER', 'EMPLOYEE'}

	# Initializes the team service and ensures Firebase is ready.
	def __init__(self) -> None:
		ensure_firebase_initialized()

	# Creates a new team in the user's organization.
	async def create_team(self, *, uid: str, name: str, description: str | None) -> Dict:
		membership = self._get_membership(uid)
		self._require_admin(membership)
		normalized_name = self._normalize_text(name)
		if not normalized_name:
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Team name is required')
		return await asyncio.to_thread(
			self._create_team_sync,
			membership['orgId'],
			uid,
			normalized_name,
			(description or '').strip(),
		)

	# Renames an existing team.
	async def rename_team(self, *, uid: str, team_id: str, name: str, description: str | None) -> Dict:
		membership = self._get_membership(uid)
		self._require_admin(membership)
		normalized_name = self._normalize_text(name)
		if not normalized_name:
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Team name is required')
		return await asyncio.to_thread(
			self._rename_team_sync,
			membership['orgId'],
			team_id,
			normalized_name,
			(description or '').strip(),
		)

	# Deletes a team and all its memberships.
	async def delete_team(self, *, uid: str, team_id: str) -> Dict:
		membership = self._get_membership(uid)
		self._require_admin(membership)
		return await asyncio.to_thread(
			self._delete_team_sync,
			membership['orgId'],
			team_id,
		)

	# Adds a member to a team with a specified role.
	async def add_member(self, *, uid: str, team_id: str, target_uid: str, role: str) -> Dict:
		membership = self._get_membership(uid)
		self._require_admin(membership)
		role_value = self._normalize_role(role)
		return await asyncio.to_thread(
			self._add_member_sync,
			membership['orgId'],
			team_id,
			target_uid,
			role_value,
			uid,
		)

	# Updates a team member's role.
	async def update_member_role(self, *, uid: str, team_id: str, target_uid: str, role: str) -> Dict:
		membership = self._get_membership(uid)
		self._require_admin(membership)
		role_value = self._normalize_role(role)
		return await asyncio.to_thread(
			self._update_member_role_sync,
			membership['orgId'],
			team_id,
			target_uid,
			role_value,
		)

	# Removes a member from a team.
	async def remove_member(self, *, uid: str, team_id: str, target_uid: str) -> Dict:
		membership = self._get_membership(uid)
		self._require_admin(membership)
		return await asyncio.to_thread(
			self._remove_member_sync,
			membership['orgId'],
			team_id,
			target_uid,
		)

	# Synchronously creates a team document in Firestore.
	def _create_team_sync(self, org_id: str, creator_uid: str, name: str, description: str) -> Dict:
		client = self._get_client()
		team_ref = client.collection('teams').document()
		payload = {
			'orgId': org_id,
			'name': name,
			'description': description,
			'createdBy': creator_uid,
			'createdAt': firestore.SERVER_TIMESTAMP,
		}
		team_ref.set(payload)
		logger.info('Team %s created in org %s', team_ref.id, org_id)
		return {
			'teamId': team_ref.id,
			'orgId': org_id,
			'name': name,
			'description': description,
		}

	# Synchronously updates a team's name and description.
	def _rename_team_sync(self, org_id: str, team_id: str, name: str, description: str) -> Dict:
		client = self._get_client()
		team_ref = client.collection('teams').document(team_id)
		team_snapshot = team_ref.get()
		if not team_snapshot.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Team not found')
		team_data = team_snapshot.to_dict() or {}
		if team_data.get('orgId') != org_id:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot modify team in another organization')
		team_ref.update({'name': name, 'description': description})
		logger.info('Team %s renamed in org %s', team_id, org_id)
		return {
			'teamId': team_id,
			'orgId': org_id,
			'name': name,
			'description': description,
		}

	# Synchronously deletes a team and all its members.
	def _delete_team_sync(self, org_id: str, team_id: str) -> Dict:
		client = self._get_client()
		self._ensure_team_in_org(client, team_id, org_id)
		
		member_docs = client.collection('team_members').where('teamId', '==', team_id).stream()
		deleted_members = 0
		for member_doc in member_docs:
			member_doc.reference.delete()
			deleted_members += 1
		
		client.collection('teams').document(team_id).delete()
		logger.info('Deleted team %s from org %s (removed %d members)', team_id, org_id, deleted_members)
		return {'teamId': team_id, 'deleted': True, 'membersRemoved': deleted_members}

	# Synchronously adds a member to a team.
	def _add_member_sync(self, org_id: str, team_id: str, target_uid: str, role: str, acting_uid: str) -> Dict:
		client = self._get_client()
		team_doc = self._ensure_team_in_org(client, team_id, org_id)
		target_member = self._get_org_member(client, org_id, target_uid)

		team_members_collection = client.collection('team_members')
		member_ref = team_members_collection.document(f'{team_id}_{target_uid}')
		payload = {
			'teamId': team_id,
			'orgId': org_id,
			'uid': target_uid,
			'email': target_member.get('email'),
			'role': role,
			'addedBy': acting_uid,
			'addedAt': firestore.SERVER_TIMESTAMP,
		}
		member_ref.set(payload)
		logger.info('User %s added to team %s with role %s', target_uid, team_id, role)
		return {
			'teamId': team_id,
			'teamName': team_doc.get('name', ''),
			'uid': target_uid,
			'role': role,
			'email': target_member.get('email'),
		}

	# Synchronously updates a team member's role.
	def _update_member_role_sync(self, org_id: str, team_id: str, target_uid: str, role: str) -> Dict:
		client = self._get_client()
		self._ensure_team_in_org(client, team_id, org_id)
		member_ref = client.collection('team_members').document(f'{team_id}_{target_uid}')
		member_doc = member_ref.get()
		if not member_doc.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Member not found in team')
		member_ref.update({'role': role})
		logger.info('Updated role for %s in team %s to %s', target_uid, team_id, role)
		member_data = member_doc.to_dict() or {}
		member_data['role'] = role
		return {
			'teamId': team_id,
			'uid': target_uid,
			'role': role,
			'email': member_data.get('email'),
		}

	# Synchronously removes a member from a team.
	def _remove_member_sync(self, org_id: str, team_id: str, target_uid: str) -> Dict:
		client = self._get_client()
		self._ensure_team_in_org(client, team_id, org_id)
		member_ref = client.collection('team_members').document(f'{team_id}_{target_uid}')
		member_doc = member_ref.get()
		if not member_doc.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Member not found in team')
		member_ref.delete()
		logger.info('Removed user %s from team %s', target_uid, team_id)
		return {'teamId': team_id, 'uid': target_uid}

	# Retrieves and validates the user's organization membership.
	def _get_membership(self, uid: str) -> Dict:
		client = self._get_client()
		docs = list(client.collection('org_members').where('uid', '==', uid).limit(1).stream())
		if not docs:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User is not part of any organization')
		doc = docs[0]
		data = doc.to_dict() or {}
		data['orgId'] = data.get('orgId')
		if not data['orgId']:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Organization membership is invalid')
		return data

	# Raises an error if the user is not an admin.
	def _require_admin(self, membership: Dict) -> None:
		if membership.get('role') != 'ORG_ADMIN':
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Administrator privileges required')

	# Validates that a team belongs to the specified organization.
	def _ensure_team_in_org(self, client, team_id: str, org_id: str) -> Dict:
		team_doc = client.collection('teams').document(team_id).get()
		if not team_doc.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Team not found')
		team_data = team_doc.to_dict() or {}
		if team_data.get('orgId') != org_id:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Team belongs to another organization')
		return team_data

	# Retrieves an organization member by ID.
	def _get_org_member(self, client, org_id: str, target_uid: str) -> Dict:
		member_ref = client.collection('org_members').document(f'{org_id}_{target_uid}')
		member_doc = member_ref.get()
		if not member_doc.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User is not part of this organization')
		return member_doc.to_dict() or {}

	# Normalizes and validates a team role.
	def _normalize_role(self, role: str) -> str:
		value = (role or '').upper()
		if value not in self.VALID_TEAM_ROLES:
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Role must be MANAGER or EMPLOYEE')
		return value

	# Normalizes text by collapsing whitespace.
	@staticmethod
	def _normalize_text(value: str | None) -> str:
		if value is None:
			return ''
		return ' '.join(value.split())

	# Returns the Firestore client instance.
	@staticmethod
	def _get_client():
		ensure_firebase_initialized()
		return firestore.client()


default_team_service = TeamService()
team_service = default_team_service
