import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class Participant:

                                                                            
	def __init__(self, zoom_user_id: str, display_name: str, join_time: datetime):
		self.zoom_user_id = zoom_user_id
		self.display_name = display_name
		self.join_time = join_time

                                             
	def to_dict(self) -> Dict:
		return {
		 'zoomUserId': self.zoom_user_id,
		 'displayName': self.display_name,
		 'joinTime': self.join_time.isoformat() if isinstance(self.join_time, datetime) else self.join_time,
		}


class MeetingSession:

                                                         
	def __init__(self, meeting_id: str, org_id: str, team_id: str, started_at: datetime):
		self.meeting_id = meeting_id
		self.org_id = org_id
		self.team_id = team_id
		self.started_at = started_at
		self.participants: List[Participant] = []

                                                          
	def add_participant(self, zoom_user_id: str, display_name: str) -> None:
		if any(p.zoom_user_id == zoom_user_id for p in self.participants):
			logger.info('Participant %s already in session %s', zoom_user_id, self.meeting_id)
			return
		participant = Participant(zoom_user_id, display_name, datetime.now(timezone.utc))
		self.participants.append(participant)
		logger.info('Added participant %s to meeting session %s', display_name, self.meeting_id)

                                         
	def to_dict(self) -> Dict:
		return {
		 'meetingId': self.meeting_id,
		 'orgId': self.org_id,
		 'teamId': self.team_id,
		 'startedAt': self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
		 'participants': [p.to_dict() for p in self.participants],
		}


class MeetingSessionService:

                                                        
	def __init__(self) -> None:
		ensure_firebase_initialized()
		self._sessions: Dict[str, MeetingSession] = {}

                                         
	def _get_client(self):
		ensure_firebase_initialized()
		return firestore.client()

                                                         
	def start_session(self, meeting_id: str, zoom_meeting_id: str, org_id: str, team_id: str) -> MeetingSession:
		now = datetime.now(timezone.utc)
		key = str(zoom_meeting_id)
		session = MeetingSession(meeting_id, org_id, team_id, now)
		self._sessions[key] = session
		logger.info('Started session for meeting %s (zoom=%s)', meeting_id, key)
		return session

                                                  
	def get_session(self, zoom_meeting_id: str) -> Optional[MeetingSession]:
		return self._sessions.get(str(zoom_meeting_id))

                                           
	def add_participant(self, zoom_meeting_id: str, zoom_user_id: str, display_name: str) -> None:
		session = self._sessions.get(str(zoom_meeting_id))
		if not session:
			logger.warning('No session found for zoom meeting %s when adding participant', zoom_meeting_id)
			return
		session.add_participant(zoom_user_id, display_name)

                                                
	def end_session(self, zoom_meeting_id: str) -> Optional[MeetingSession]:
		session = self._sessions.pop(str(zoom_meeting_id), None)
		if session:
			logger.info('Ended session for meeting %s', session.meeting_id)
		return session

                                                                   
	def update_firestore_meeting_status(self, zoom_meeting_id: str, status: str) -> None:
		client = self._get_client()
		zoom_id_str = str(zoom_meeting_id)
		logger.info('Updating meeting status for zoomMeetingId=%s (type=%s) -> %s', zoom_id_str, type(zoom_meeting_id).__name__, status)
		meetings = list(client.collection('meetings').where('zoomMeetingId', '==', zoom_id_str).limit(1).stream())
		if not meetings and zoom_id_str.isdigit():
			logger.info('No meeting found with string id %s, retrying as int', zoom_id_str)
			meetings = list(
			 client.collection('meetings')
			 .where('zoomMeetingId', '==', int(zoom_id_str))
			 .limit(1)
			 .stream()
			)
		if not meetings:
			logger.warning('No Firestore meeting found for zoom id %s', zoom_meeting_id)
			return
		doc = meetings[0]
		update = {'status': status}
		if status == 'ACTIVE':
			update['startedAt'] = firestore.SERVER_TIMESTAMP
		elif status == 'ENDED':
			update['endedAt'] = firestore.SERVER_TIMESTAMP
		doc.reference.update(update)
		logger.info('Updated Firestore meeting %s to status %s', doc.id, status)


default_session_service = MeetingSessionService()
meeting_session_service = default_session_service