import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class ExtensionSessionService:

	COLLECTION_NAME = 'extension_sessions'
	MEMBERS_COLLECTION = 'org_members'
	DEFAULT_TTL_HOURS = 24

                                                           
	def __init__(self, ttl_hours: int = DEFAULT_TTL_HOURS) -> None:
		self.ttl_hours = ttl_hours
		ensure_firebase_initialized()

                                                                 
	async def create_session(self, *, uid: str | None, email: str | None, org_id: str | None) -> dict:
		if not uid:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Missing user id')
		if not org_id:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Organization id is required')

		return await asyncio.to_thread(self._create_session_sync, uid, email or '', org_id)

                                                        
	async def verify_session(self, session_id: str | None) -> dict:
		if not session_id:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Session id is required')

		return await asyncio.to_thread(self._verify_session_sync, session_id)

                                                                    
	def _create_session_sync(self, uid: str, email: str, org_id: str) -> dict:
		client = self._get_client()
		member_ref = client.collection(self.MEMBERS_COLLECTION).document(f'{org_id}_{uid}')
		member_snapshot = member_ref.get()
		if not member_snapshot.exists:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User does not belong to this organization')

		session_id = secrets.token_urlsafe(48)
		now = datetime.now(timezone.utc)
		expires_at = now + timedelta(hours=self.ttl_hours)

		session_payload = {
		 'sessionId': session_id,
		 'uid': uid,
		 'email': email,
		 'orgId': org_id,
		 'createdAt': now,
		 'expiresAt': expires_at,
		 'revoked': False,
		}

		collection = client.collection(self.COLLECTION_NAME)
		collection.document(session_id).set(session_payload)
		logger.info('Extension session created for uid %s in org %s', uid, org_id)

		return {
		 'sessionId': session_id,
		 'expiresAt': expires_at,
		}

                                                                                  
	def _verify_session_sync(self, session_id: str) -> dict:
		client = self._get_client()
		doc_ref = client.collection(self.COLLECTION_NAME).document(session_id)
		snapshot = doc_ref.get()
		if not snapshot.exists:
			raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Session not found')

		data = snapshot.to_dict() or {}
		if data.get('revoked'):
			raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Session revoked')

		expires_at = data.get('expiresAt')
		if isinstance(expires_at, datetime):
			if expires_at.tzinfo is None:
				expires_at = expires_at.replace(tzinfo=timezone.utc)
			if expires_at <= datetime.now(timezone.utc):
				raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Session expired')

		uid = data.get('uid')
		org_id = data.get('orgId')
		if not uid or not org_id:
			raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Session record is incomplete')

		return {
		 'uid': uid,
		 'email': data.get('email'),
		 'orgId': org_id,
		}

                                         
	@staticmethod
	def _get_client():
		ensure_firebase_initialized()
		return firestore.client()


default_extension_session_service = ExtensionSessionService()
extension_session_service = default_extension_session_service
