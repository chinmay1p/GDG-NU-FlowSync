import asyncio
import logging
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class ContextService:

	CHUNK_SIZE = 10

	# Initializes the context service and ensures Firebase is ready.
	def __init__(self) -> None:
		ensure_firebase_initialized()

	# Retrieves the full organization and team context for a user.
	async def get_user_context(self, *, uid: str, email: str | None) -> Dict:
		if not uid:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Missing user id')
		return await asyncio.to_thread(self._build_context_sync, uid, email)

	# Synchronously builds the user context including org, teams, and members.
	def _build_context_sync(self, uid: str, email: str | None) -> Dict:
		client = firestore.client()

		org_members_collection = client.collection('org_members')
		membership_docs = list(org_members_collection.where('uid', '==', uid).limit(1).stream())
		if not membership_docs:
			return {
				'uid': uid,
				'email': email,
				'hasOrg': False,
				'orgId': None,
				'orgRole': None,
				'organization': None,
				'teams': [],
				'orgTeams': [],
				'orgMembers': [],
			}

		membership_data = membership_docs[0].to_dict() or {}
		org_id = membership_data.get('orgId')
		org_role = membership_data.get('role', 'MEMBER')

		if not org_id:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Organization membership record is invalid')

		org_doc = client.collection('organizations').document(org_id).get()
		if not org_doc.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Organization not found')

		org_data = org_doc.to_dict() or {}
		organization_payload = {
			'orgId': org_doc.id,
			'name': org_data.get('name', ''),
			'description': org_data.get('description', ''),
			'joinCode': org_data.get('joinCode') if org_role == 'ORG_ADMIN' else None,
		}

		user_team_docs = list(client.collection('team_members').where('uid', '==', uid).stream())
		user_team_roles: Dict[str, str] = {}
		for doc in user_team_docs:
			data = doc.to_dict() or {}
			team_id = data.get('teamId')
			if team_id:
				user_team_roles[team_id] = data.get('role', 'EMPLOYEE')

		teams_collection = client.collection('teams')
		team_docs: List = []
		if org_role == 'ORG_ADMIN':
			team_docs = list(teams_collection.where('orgId', '==', org_id).stream())
		else:
			for team_id in user_team_roles.keys():
				doc = teams_collection.document(team_id).get()
				if doc.exists:
					team_docs.append(doc)

		team_members_map: Dict[str, List[Dict]] = defaultdict(list)
		team_ids = [doc.id for doc in team_docs]
		if team_ids:
			team_members_collection = client.collection('team_members')
			for chunk in self._chunk(team_ids):
				chunk_members = list(team_members_collection.where('teamId', 'in', chunk).stream())
				for member_doc in chunk_members:
					member_data = member_doc.to_dict() or {}
					team_id = member_data.get('teamId')
					if not team_id:
						continue
					team_members_map[team_id].append({
						'uid': member_data.get('uid'),
						'email': member_data.get('email'),
						'role': member_data.get('role', 'MEMBER'),
					})

		org_teams: List[Dict] = []
		team_lookup: Dict[str, Dict] = {}
		for team_doc in team_docs:
			team_data = team_doc.to_dict() or {}
			payload = {
				'teamId': team_doc.id,
				'teamName': team_data.get('name', 'Untitled Team'),
				'description': team_data.get('description', ''),
				'members': team_members_map.get(team_doc.id, []),
			}
			team_lookup[team_doc.id] = payload
			org_teams.append(payload)

		user_teams: List[Dict] = []
		for team_id, role in user_team_roles.items():
			team_entry = team_lookup.get(team_id)
			if not team_entry:
				continue
			user_teams.append({
				'teamId': team_entry['teamId'],
				'teamName': team_entry['teamName'],
				'role': role,
				'members': team_entry['members'],
			})

		org_members_payload: List[Dict] = []
		if org_role == 'ORG_ADMIN':
			org_member_docs = org_members_collection.where('orgId', '==', org_id).stream()
			for member_doc in org_member_docs:
				member_data = member_doc.to_dict() or {}
				org_members_payload.append({
					'uid': member_data.get('uid'),
					'email': member_data.get('email'),
					'role': member_data.get('role', 'MEMBER'),
				})

		response = {
			'uid': uid,
			'email': email,
			'hasOrg': True,
			'orgId': org_id,
			'orgRole': org_role,
			'organization': organization_payload,
			'teams': user_teams,
			'orgTeams': org_teams,
			'orgMembers': org_members_payload,
		}

		logger.info('Context resolved for user %s in org %s', uid, org_id)
		return response

	# Yields chunks of items for batched Firestore queries.
	def _chunk(self, items: List[str]):
		for index in range(0, len(items), self.CHUNK_SIZE):
			yield items[index:index + self.CHUNK_SIZE]


default_context_service = ContextService()
context_service = default_context_service
