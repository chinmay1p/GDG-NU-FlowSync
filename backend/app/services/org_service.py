import asyncio
import logging
import random
from typing import Dict

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class OrgService:

	CODE_LENGTH = 6
	MAX_CODE_ATTEMPTS = 20

                                                                      
	def __init__(self) -> None:
		ensure_firebase_initialized()

                                                     
	async def create_organization(self, *, uid: str, email: str | None, name: str, description: str | None) -> Dict[str, str]:
		if not uid:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Missing user id')
		if not email:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Verified email required to create an organization')

		normalized_name = self._normalize_text(name)
		if not normalized_name:
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Organization name is required')

		normalized_description = (description or '').strip()

		return await asyncio.to_thread(
		 self._create_org_sync,
		 uid,
		 email,
		 normalized_name,
		 normalized_description,
		)

                                                    
	async def join_organization(self, *, uid: str, email: str | None, join_code: str) -> Dict[str, str]:
		if not uid:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Missing user id')
		if not email:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Verified email required to join an organization')

		normalized_code = (join_code or '').strip()
		if not normalized_code:
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Join code is required')

		return await asyncio.to_thread(self._join_org_sync, uid, email, normalized_code)

                                                                            
	def _create_org_sync(self, uid: str, email: str, name: str, description: str) -> Dict[str, str]:
		client = self._get_client()
		orgs_collection = client.collection('organizations')
		members_collection = client.collection('org_members')

		join_code = self._generate_unique_join_code(orgs_collection)
		org_ref = orgs_collection.document()
		org_id = org_ref.id
		member_ref = members_collection.document(f'{org_id}_{uid}')

		org_payload = {
		 'name': name,
		 'description': description,
		 'createdBy': uid,
		 'createdAt': firestore.SERVER_TIMESTAMP,
		 'joinCode': join_code,
		 'settings': {},
		}

		member_payload = {
		 'orgId': org_id,
		 'uid': uid,
		 'email': email,
		 'role': 'ORG_ADMIN',
		 'joinedAt': firestore.SERVER_TIMESTAMP,
		}

		batch = client.batch()
		batch.set(org_ref, org_payload)
		batch.set(member_ref, member_payload)
		batch.commit()

		logger.info('Organization %s created by %s', org_id, uid)
		return {'orgId': org_id, 'joinCode': join_code}

                                                                        
	def _join_org_sync(self, uid: str, email: str, join_code: str) -> Dict[str, str]:
		client = self._get_client()
		orgs_collection = client.collection('organizations')
		members_collection = client.collection('org_members')

		matching_orgs = list(orgs_collection.where('joinCode', '==', join_code).limit(1).stream())
		if not matching_orgs:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Invalid join code')

		org_snapshot = matching_orgs[0]
		org_id = org_snapshot.id
		member_doc_id = f'{org_id}_{uid}'
		member_ref = members_collection.document(member_doc_id)

		if member_ref.get().exists:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='User already belongs to this organization')

		member_payload = {
		 'orgId': org_id,
		 'uid': uid,
		 'email': email,
		 'role': 'MEMBER',
		 'joinedAt': firestore.SERVER_TIMESTAMP,
		}

		member_ref.set(member_payload)
		logger.info('User %s joined organization %s via join code', uid, org_id)
		return {'orgId': org_id, 'role': 'MEMBER'}

                                            
	@staticmethod
	def _normalize_text(value: str | None) -> str:
		if value is None:
			return ''
		return ' '.join(value.split())

                                                            
	def _generate_unique_join_code(self, orgs_collection) -> str:
		for _ in range(self.MAX_CODE_ATTEMPTS):
			code = f'{random.randint(0, 10**self.CODE_LENGTH - 1):0{self.CODE_LENGTH}d}'
			if not list(orgs_collection.where('joinCode', '==', code).limit(1).stream()):
				return code
		raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Unable to generate join code. Please retry.')

                                         
	@staticmethod
	def _get_client():
		ensure_firebase_initialized()
		return firestore.client()


default_org_service = OrgService()
org_service = default_org_service
