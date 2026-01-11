import base64
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import requests
from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)

ZOOM_ACCOUNT_ID = os.getenv('ZOOM_ACCOUNT_ID')
ZOOM_CLIENT_ID = os.getenv('ZOOM_CLIENT_ID')
ZOOM_CLIENT_SECRET = os.getenv('ZOOM_CLIENT_SECRET')

class ZoomService:

	TOKEN_URL = 'https://zoom.us/oauth/token'
	CREATE_MEETING_URL = 'https://api.zoom.us/v2/users/me/meetings'

	# Initializes the Zoom service with token cache.
	def __init__(self) -> None:
		ensure_firebase_initialized()
		self._access_token: Optional[str] = None
		self._token_expiry_ts: float = 0.0

	# Returns the Firestore client instance.
	def _get_client(self):
		ensure_firebase_initialized()
		return firestore.client()

	# Generates the Basic auth header for Zoom OAuth.
	def _basic_auth_header(self) -> str:
		if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
			raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Zoom client credentials are not configured')
		creds = f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode('utf-8')
		return 'Basic ' + base64.b64encode(creds).decode('utf-8')

	# Fetches a new OAuth token from Zoom.
	def _fetch_token(self) -> None:
		if not ZOOM_ACCOUNT_ID:
			raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Zoom account id is not configured')
		headers = {
			'Authorization': self._basic_auth_header(),
		}
		params = {
			'grant_type': 'account_credentials',
			'account_id': ZOOM_ACCOUNT_ID,
		}
		resp = requests.post(self.TOKEN_URL, headers=headers, params=params, timeout=15)
		if resp.status_code != 200:
			logger.error('Zoom token fetch failed: %s %s', resp.status_code, resp.text)
			raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Failed to fetch Zoom OAuth token')
		data = resp.json()
		self._access_token = data.get('access_token')
		expires_in = float(data.get('expires_in') or 0)
		self._token_expiry_ts = time.time() + max(expires_in - 30.0, 0.0)
		logger.info('Obtained Zoom token; expires in %ss', int(expires_in))

	# Returns a valid access token, refreshing if needed.
	def _get_token(self) -> str:
		if self._access_token and time.time() < self._token_expiry_ts:
			return self._access_token
		self._fetch_token()
		return self._access_token or ''

	# Retrieves the user's organization and team context.
	def _get_user_org_context(self, uid: str) -> Dict:
		client = self._get_client()
		membership_docs = list(client.collection('org_members').where('uid', '==', uid).limit(1).stream())
		if not membership_docs:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='User is not part of any organization')
		membership = membership_docs[0].to_dict() or {}
		org_id = membership.get('orgId')
		role = (membership.get('role') or '').upper() or 'EMPLOYEE'
		if not org_id:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Organization not found for user')
		manager_team_ids: set[str] = set()
		member_team_ids: set[str] = set()
		team_membership_docs = client.collection('team_members').where('uid', '==', uid).stream()
		for doc in team_membership_docs:
			entry = doc.to_dict() or {}
			team_id = entry.get('teamId')
			if not team_id:
				continue
			member_team_ids.add(team_id)
			if (entry.get('role') or '').upper() == 'MANAGER':
				manager_team_ids.add(team_id)
		return {
			'orgId': org_id,
			'role': role,
			'managerTeamIds': list(manager_team_ids),
			'memberTeamIds': list(member_team_ids),
		}

	# Validates that the user is an admin or manager of the team.
	def _require_admin_or_manager(self, uid: str, team_id: Optional[str]) -> Dict:
		ctx = self._get_user_org_context(uid)
		if ctx['role'] == 'ORG_ADMIN':
			return ctx
		if team_id and team_id in ctx['managerTeamIds']:
			return ctx
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only admins or team managers can create Zoom meetings')

	# Parses and normalizes an ISO 8601 start time string.
	@staticmethod
	def _parse_start_time(value: str) -> str:
		try:
			dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
			if dt.tzinfo is None:
				dt = dt.replace(tzinfo=timezone.utc)
			return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
		except Exception:
			logger.exception('Failed to parse start time value=%s', value)
			raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='startTime must be a valid ISO 8601 string')

	# Creates a Zoom meeting and persists it to Firestore.
	def create_meeting(self, *, uid: str, team_id: str, topic: str, start_time: str, duration_minutes: int) -> Dict:
		logger.info('Zoom meeting create requested uid=%s team=%s startTime=%s duration=%s', uid, team_id, start_time, duration_minutes)
		ctx = self._require_admin_or_manager(uid, team_id)
		org_id = ctx['orgId']
		access_token = self._get_token()
		if not access_token:
			raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Zoom OAuth token unavailable')
		normalized_topic = (topic or '').strip() or 'Scheduled Meeting'
		normalized_start = self._parse_start_time(start_time)
		logger.info('Zoom meeting normalized start time %s', normalized_start)
		duration = int(duration_minutes or 30)
		payload = {
			'topic': normalized_topic,
			'type': 2,
			'start_time': normalized_start,
			'duration': duration,
		}
		headers = {
			'Authorization': f'Bearer {access_token}',
			'Content-Type': 'application/json',
		}
		resp = requests.post(self.CREATE_MEETING_URL, json=payload, headers=headers, timeout=20)
		if resp.status_code not in (200, 201):
			logger.error('Zoom meeting create failed: %s %s', resp.status_code, resp.text)
			raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Failed to create Zoom meeting')
		z = resp.json()
		join_url = z.get('join_url')
		start_url = z.get('start_url')
		zoom_meeting_id_raw = z.get('id')
		zoom_meeting_id = str(zoom_meeting_id_raw) if zoom_meeting_id_raw is not None else None
		logger.info('Zoom meeting created id=%s (type=%s)', zoom_meeting_id, type(zoom_meeting_id_raw).__name__)
		client = self._get_client()
		meeting_ref = client.collection('meetings').document()
		meeting_id = meeting_ref.id
		now_iso = datetime.now(timezone.utc).isoformat()
		doc = {
			'meetingId': meeting_id,
			'zoomMeetingId': zoom_meeting_id,
			'joinUrl': join_url,
			'startUrl': start_url,
			'createdBy': uid,
			'teamId': team_id,
			'orgId': org_id,
			'status': 'SCHEDULED',
			'topic': normalized_topic,
			'startTime': normalized_start,
			'durationMinutes': duration,
			'createdAt': firestore.SERVER_TIMESTAMP,
		}
		meeting_ref.set(doc)
		logger.info('Zoom meeting %s created (zoom id=%s) for org %s team %s', meeting_id, zoom_meeting_id, org_id, team_id)
		return {**doc, 'createdAt': now_iso}

	# Serializes a timestamp value to ISO string.
	@staticmethod
	def _serialize_timestamp(value):
		if value is None:
			return None
		if hasattr(value, 'to_datetime'):
			return value.to_datetime(timezone.utc).isoformat()
		if isinstance(value, datetime):
			if value.tzinfo is None:
				value = value.replace(tzinfo=timezone.utc)
			return value.astimezone(timezone.utc).isoformat()
		return value

	# Serializes a meeting document for API response.
	def _serialize_meeting_doc(self, data: Dict) -> Dict:
		result = dict(data)
		for key in ('createdAt', 'startedAt', 'endedAt', 'startTime'):
			if key in result:
				result[key] = self._serialize_timestamp(result.get(key))
		if 'status' not in result:
			result['status'] = 'SCHEDULED'
		return result

	# Lists meetings visible to the user based on their role.
	def list_meetings_for_user(self, uid: str, limit: int = 50) -> list[Dict]:
		logger.info('Listing meetings for uid=%s', uid)
		ctx = self._get_user_org_context(uid)
		role = (ctx['role'] or 'EMPLOYEE').upper()
		client = self._get_client()
		query = client.collection('meetings').where('orgId', '==', ctx['orgId']).limit(limit)
		docs = list(query.stream())
		manager_team_ids = set(ctx.get('managerTeamIds') or [])
		member_team_ids = set(ctx.get('memberTeamIds') or [])
		viewable_team_ids = member_team_ids or manager_team_ids
		items: list[Dict] = []
		for doc in docs:
			payload = doc.to_dict() or {}
			team_id = payload.get('teamId')
			if role != 'ORG_ADMIN':
				if not team_id:
					continue
				if role == 'MANAGER' and (team_id in manager_team_ids or team_id in viewable_team_ids):
					pass
				elif role != 'MANAGER' and team_id in viewable_team_ids:
					pass
				else:
					continue
			items.append(self._serialize_meeting_doc(payload))
		items.sort(key=lambda item: item.get('createdAt') or '', reverse=True)
		return items


zoom_service = ZoomService()