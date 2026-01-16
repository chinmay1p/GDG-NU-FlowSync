import logging
from fastapi import APIRouter, Request
from starlette.responses import PlainTextResponse

from app.services.meeting_session_service import meeting_session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/zoom', tags=['zoom-webhook'])


@router.post('/webhook')
async def zoom_webhook(request: Request):
	"""
	Zoom webhook endpoint for meeting lifecycle events.
	Handles:
	- Webhook validation (challenge)
	- meeting.started
	- meeting.participant_joined
	- meeting.ended
	"""
	body = await request.json()

                                      
	if body.get('type') == 'url_validation':
		challenge = body.get('challenge')
		if challenge:
			logger.info('Zoom webhook validation challenge received')
			return {'challenge': challenge}

                     
	event_type = body.get('event')
	payload = body.get('payload') or {}
	object_data = payload.get('object') or {}

	try:
		if event_type == 'meeting.started':
			_handle_meeting_started(object_data)
		elif event_type == 'meeting.participant_joined':
			_handle_participant_joined(object_data)
		elif event_type == 'meeting.ended':
			_handle_meeting_ended(object_data)
		else:
			logger.info('Zoom webhook %s (no handler)', event_type)
	except Exception as exc:                
		logger.exception('Error processing Zoom webhook %s: %s', event_type, exc)

	return {'status': 'ok'}


def _handle_meeting_started(object_data: dict) -> None:
	"""meeting.started event handler."""
	zoom_meeting_id_raw = object_data.get('id')
	if not zoom_meeting_id_raw:
		logger.warning('meeting.started missing meeting id')
		return
	zoom_meeting_id = str(zoom_meeting_id_raw)
	logger.info('Zoom meeting %s started (type=%s)', zoom_meeting_id, type(zoom_meeting_id_raw).__name__)

                                  
	meeting_session_service.update_firestore_meeting_status(zoom_meeting_id, 'ACTIVE')

                                               
	from app.core.security import ensure_firebase_initialized
	from firebase_admin import firestore

	ensure_firebase_initialized()
	client = firestore.client()
	meetings = list(client.collection('meetings').where('zoomMeetingId', '==', zoom_meeting_id).limit(1).stream())
	if not meetings and zoom_meeting_id.isdigit():
		logger.info('Retrying meeting lookup for zoom id %s as int', zoom_meeting_id)
		meetings = list(
		 client.collection('meetings')
		 .where('zoomMeetingId', '==', int(zoom_meeting_id))
		 .limit(1)
		 .stream()
		)
	if meetings:
		meeting_doc = meetings[0].to_dict() or {}
		meeting_id = meeting_doc.get('meetingId')
		org_id = meeting_doc.get('orgId')
		team_id = meeting_doc.get('teamId')

                           
		if meeting_id and org_id and team_id:
			meeting_session_service.start_session(meeting_id, zoom_meeting_id, org_id, team_id)

                                                            
		if meeting_id and org_id:
			import asyncio
			asyncio.create_task(_emit_start_bot_event(meeting_id, zoom_meeting_id, org_id, team_id))
	else:
		logger.warning('No Firestore meeting found for zoom id %s', zoom_meeting_id)


async def _emit_start_bot_event(meeting_id: str, zoom_meeting_id: str, org_id: str, team_id: str | None) -> None:
	"""Emit START_BOT WebSocket event to all org members."""
	from app.services.websocket_manager import websocket_manager
	from app.core.security import ensure_firebase_initialized
	from firebase_admin import firestore

	try:
		ensure_firebase_initialized()
		client = firestore.client()

                                 
		org_members = client.collection('org_members').where('orgId', '==', org_id).stream()
  
		payload = {
		 'meetingId': meeting_id,
		 'zoomMeetingNumber': zoom_meeting_id,
		 'teamId': team_id,
		}

		notified_count = 0
		for member_doc in org_members:
			member_data = member_doc.to_dict() or {}
			user_id = member_data.get('uid')
			if user_id:
				await websocket_manager.emit_to_user(user_id, 'START_BOT', payload)
				notified_count += 1

		logger.info('START_BOT event emitted to %d users for meeting %s', notified_count, meeting_id)

	except Exception as exc:
		logger.warning('Failed to emit START_BOT event for meeting %s: %s', meeting_id, exc)


def _handle_participant_joined(object_data: dict) -> None:
	"""meeting.participant_joined event handler."""
	zoom_meeting_id_raw = object_data.get('id')
	participant_data = object_data.get('participant') or {}

	if not zoom_meeting_id_raw:
		logger.warning('meeting.participant_joined missing meeting id')
		return
	zoom_meeting_id = str(zoom_meeting_id_raw)

	zoom_user_id = participant_data.get('id')
	display_name = participant_data.get('name', 'Unknown')

	if not zoom_user_id:
		logger.warning('meeting.participant_joined missing participant id')
		return

	logger.info('Participant %s joined zoom meeting %s', display_name, zoom_meeting_id)
	meeting_session_service.add_participant(zoom_meeting_id, zoom_user_id, display_name)


def _handle_meeting_ended(object_data: dict) -> None:
	"""meeting.ended event handler."""
	zoom_meeting_id_raw = object_data.get('id')
	if not zoom_meeting_id_raw:
		logger.warning('meeting.ended missing meeting id')
		return
	zoom_meeting_id = str(zoom_meeting_id_raw)
	logger.info('Zoom meeting %s ended (type=%s)', zoom_meeting_id, type(zoom_meeting_id_raw).__name__)

                                  
	meeting_session_service.update_firestore_meeting_status(zoom_meeting_id, 'ENDED')

                                                      
	from app.core.security import ensure_firebase_initialized
	from firebase_admin import firestore

	ensure_firebase_initialized()
	client = firestore.client()
	meetings = list(client.collection('meetings').where('zoomMeetingId', '==', zoom_meeting_id).limit(1).stream())
	if not meetings and zoom_meeting_id.isdigit():
		meetings = list(
		 client.collection('meetings')
		 .where('zoomMeetingId', '==', int(zoom_meeting_id))
		 .limit(1)
		 .stream()
		)

	if meetings:
		meeting_doc = meetings[0].to_dict() or {}
		meeting_id = meeting_doc.get('meetingId')
		org_id = meeting_doc.get('orgId')
		team_id = meeting_doc.get('teamId')

		if meeting_id and org_id:
			import asyncio
                                                 
			asyncio.create_task(_emit_stop_bot_event(meeting_id, zoom_meeting_id, org_id))
                             
			asyncio.create_task(_generate_meeting_summary(meeting_id, org_id))
	else:
		logger.warning('No Firestore meeting found for zoom id %s during end', zoom_meeting_id)

                            
	meeting_session_service.end_session(zoom_meeting_id)


async def _emit_stop_bot_event(meeting_id: str, zoom_meeting_id: str, org_id: str) -> None:
	"""Emit STOP_BOT WebSocket event to all org members."""
	from app.services.websocket_manager import websocket_manager
	from app.core.security import ensure_firebase_initialized
	from firebase_admin import firestore

	try:
		ensure_firebase_initialized()
		client = firestore.client()

                                 
		org_members = client.collection('org_members').where('orgId', '==', org_id).stream()
  
		payload = {
		 'meetingId': meeting_id,
		 'zoomMeetingNumber': zoom_meeting_id,
		}

		notified_count = 0
		for member_doc in org_members:
			member_data = member_doc.to_dict() or {}
			user_id = member_data.get('uid')
			if user_id:
				await websocket_manager.emit_to_user(user_id, 'STOP_BOT', payload)
				notified_count += 1

		logger.info('STOP_BOT event emitted to %d users for meeting %s', notified_count, meeting_id)

	except Exception as exc:
		logger.warning('Failed to emit STOP_BOT event for meeting %s: %s', meeting_id, exc)


async def _generate_meeting_summary(meeting_id: str, org_id: str) -> None:
	"""Generate meeting summary when meeting ends."""
	from app.services.meeting_transcript_service import meeting_transcript_service

	try:
                                                  
		result = await meeting_transcript_service.end_meeting(
		 meeting_id=meeting_id,
		 user_id='system',                    
		 org_id=org_id,
		 generate_summary=True,
		)
  
		if result.get('summaryGenerated'):
			logger.info('Summary generated for meeting %s', meeting_id)
		else:
			logger.info('No summary generated for meeting %s (may already exist or no transcript)', meeting_id)

	except Exception as exc:
		logger.warning('Failed to generate summary for meeting %s: %s', meeting_id, exc)