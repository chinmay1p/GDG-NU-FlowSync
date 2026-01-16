import asyncio
import logging
import re
from typing import Dict
from urllib.parse import urlparse

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class MeetingService:

	COLLECTION_NAME = 'meetings'
	MEET_HOST = 'meet.google.com'
	CODE_PATTERN = re.compile(r'^[a-z]{3}-[a-z]{4}-[a-z]{3}$', re.IGNORECASE)
	CONDENSED_PATTERN = re.compile(r'^[a-z]{10,12}$', re.IGNORECASE)

                                                                 
	def __init__(self) -> None:
		ensure_firebase_initialized()

                                                                         
	async def start_meeting(self, *, session: Dict, meet_url: str) -> Dict:
		normalized_url = self._normalize_meet_url(meet_url)
		if not normalized_url:
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Invalid Google Meet URL')

		uid = session.get('uid')
		org_id = session.get('orgId')
		if not uid or org_id:
			raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid session context')

		return await asyncio.to_thread(self._start_meeting_sync, session, normalized_url)

                                
	async def end_meeting(self, *, session: Dict, meeting_id: str) -> Dict:
		meeting_key = (meeting_id or '').strip()
		if not meeting_key:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Meeting id is required')

		uid = session.get('uid')
		if not uid:
			raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid session context')

		return await asyncio.to_thread(self._end_meeting_sync, session, meeting_key)

                                                         
	def _start_meeting_sync(self, session: Dict, meet_url: str) -> Dict:
		client = self._get_client()
		self._ensure_no_active_meeting(client, session['uid'])

		role = self._resolve_role(client, session)

		meeting_ref = client.collection(self.COLLECTION_NAME).document()
		payload = {
		 'meetingId': meeting_ref.id,
		 'orgId': session['orgId'],
		 'createdBy': session['uid'],
		 'email': session.get('email'),
		 'role': role,
		 'meetUrl': meet_url,
		 'startedAt': firestore.SERVER_TIMESTAMP,
		 'endedAt': None,
		 'active': True,
		}
		meeting_ref.set(payload)

		logger.info('Meeting %s started by %s in org %s', meeting_ref.id, session['uid'], session['orgId'])
		return {'meetingId': meeting_ref.id, 'role': role}

                                                      
	def _end_meeting_sync(self, session: Dict, meeting_id: str) -> Dict:
		client = self._get_client()
		meeting_ref = client.collection(self.COLLECTION_NAME).document(meeting_id)
		meeting_snapshot = meeting_ref.get()
		if not meeting_snapshot.exists:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Meeting not found')

		meeting_data = meeting_snapshot.to_dict() or {}
		if meeting_data.get('createdBy') != session['uid']:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Meeting belongs to a different user')
		if meeting_data.get('orgId') != session.get('orgId'):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Meeting belongs to a different organization')

		if meeting_data.get('active'):
			meeting_ref.update({'active': False, 'endedAt': firestore.SERVER_TIMESTAMP})
			logger.info('Meeting %s ended by %s', meeting_id, session['uid'])
			status_value = 'ENDED'
		else:
			status_value = 'ALREADY_ENDED'

		return {'meetingId': meeting_id, 'status': status_value}

                                                             
	def _ensure_no_active_meeting(self, client, uid: str) -> None:
		active_query = (
		 client.collection(self.COLLECTION_NAME)
		 .where('createdBy', '==', uid)
		 .where('active', '==', True)
		 .limit(1)
		)
		if list(active_query.stream()):
			raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='An active meeting is already running for this user')

                                                               
	def _resolve_role(self, client, session: Dict) -> str:
		org_id = session['orgId']
		uid = session['uid']

		membership_doc = client.collection('org_members').document(f'{org_id}_{uid}').get()
		if membership_doc.exists:
			membership_data = membership_doc.to_dict() or {}
			if membership_data.get('role') == 'ORG_ADMIN':
				return 'MANAGER'

		team_members = (
		 client.collection('team_members')
		 .where('uid', '==', uid)
		 .where('role', '==', 'MANAGER')
		 .limit(5)
		)
		for entry in team_members.stream():
			data = entry.to_dict() or {}
			if data.get('orgId') == org_id:
				return 'MANAGER'

		return 'EMPLOYEE'

                                              
	def _normalize_meet_url(self, meet_url: str) -> str:
		candidate = (meet_url or '').strip()
		if not candidate:
			return ''

		try:
			parsed = urlparse(candidate)
		except ValueError:
			return ''

		host = (parsed.hostname or '').lower()
		if host != self.MEET_HOST:
			return ''

		code = self._extract_meeting_code(parsed.path)
		if not code:
			return ''

		return f'https://{self.MEET_HOST}/{code.lower()}'

                                             
	def _extract_meeting_code(self, path: str | None) -> str:
		if not path:
			return ''
		trimmed = path.strip('/')
		if not trimmed:
			return ''
		first_segment = trimmed.split('/')[0]
		if self.CODE_PATTERN.match(first_segment) or self.CONDENSED_PATTERN.match(first_segment):
			return first_segment
		return ''

                                         
	@staticmethod
	def _get_client():
		ensure_firebase_initialized()
		return firestore.client()


default_meeting_service = MeetingService()
meeting_service = default_meeting_service
