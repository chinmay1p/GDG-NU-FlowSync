import base64
import binascii
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.security import verify_firebase_token_ws
from app.services.deepgram_stt import deepgram_service
from app.services.transcript_buffer import transcript_buffer_service
from app.services.websocket_manager import websocket_manager

try:
	from app.services.gemini_tasks import gemini_task_service
except ModuleNotFoundError:                                                              

	class _GeminiTaskStub:
		async def analyze_meeting(self, meeting_id, entries):                                   
			return None

		async def clear_meeting(self, meeting_id):                                   
			return None

	gemini_task_service = _GeminiTaskStub()

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket('/ws/notifications')
async def notification_socket(websocket: WebSocket):
	"""Lightweight notifications channel for authenticated users."""
	token = websocket.query_params.get('token')

	success, claims, error_reason = verify_firebase_token_ws(token)
	if not success:
		await websocket.close(code=1008, reason=error_reason)
		return

	await websocket.accept()
	user_id = claims.get('uid', 'unknown')
	try:
		await websocket_manager.register(user_id, websocket)
		while True:
                                                            
			await websocket.receive_text()
	except WebSocketDisconnect:
		logger.info('Notification websocket disconnected for user %s', user_id)
	except Exception as exc:                                    
		logger.warning('Notification websocket error for user %s: %s', user_id, exc)
	finally:
		await websocket_manager.unregister(user_id, websocket)


@router.websocket('/ws/meeting')
async def meeting_ingestion_socket(websocket: WebSocket):
	"""Authenticated WebSocket endpoint for live meeting ingestion.
	
	Flow:
	1. Extract token and meeting_id from query params
	2. Verify Firebase ID token BEFORE accepting
	3. Only accept if token is valid
	4. Log all received messages
	"""
	token = websocket.query_params.get('token')
	meeting_id = websocket.query_params.get('meeting_id')

	logger.info(
	 f'WS connection attempt from {websocket.client}: '
	 f'meeting_id={meeting_id}, token_present={bool(token)}'
	)

                      
	if not meeting_id:
		logger.warning(f'WS connection rejected: missing meeting_id')
		await websocket.close(code=1008, reason='meeting_id is required')
		return

                                             
	logger.info(f'WS token received for meeting {meeting_id}')
	success, claims, error_reason = verify_firebase_token_ws(token)

	if not success:
		logger.warning(f'WS auth failed for meeting {meeting_id}: {error_reason}')
		await websocket.close(code=1008, reason=error_reason)
		return

                                                       
	await websocket.accept()

	uid = claims.get('uid', 'unknown')
	email = claims.get('email', 'unknown')

	logger.info(f'✓ WS authenticated user {uid} ({email}) for meeting {meeting_id}')

	stt_started = False
	await transcript_buffer_service.init_meeting(meeting_id)

	async def handle_transcript(transcript_payload: dict) -> None:
		if websocket.client_state != WebSocketState.CONNECTING and websocket.client_state != WebSocketState.CONNECTED:
			return
		try:
			await websocket.send_json(transcript_payload)
		except Exception as exc:
			logger.warning('Failed to send transcript to meeting %s: %s', meeting_id, exc)

		if transcript_payload.get('is_final'):
			timestamp = transcript_payload.get('timestamp')
			if not isinstance(timestamp, int):
				timestamp = int(time.time() * 1000)
			entry = await transcript_buffer_service.add_final_transcript(
			 meeting_id,
			 text=transcript_payload.get('text', ''),
			 timestamp=timestamp,
			)
			if entry:
				final_payload = {
				 'type': 'final_transcript',
				 'meeting_id': meeting_id,
				 'text': entry.text,
				 'timestamp': entry.timestamp,
				}
				try:
					await websocket.send_json(final_payload)
				except Exception as exc:
					logger.warning('Failed to send final transcript buffer update for meeting %s: %s', meeting_id, exc)
		else:
                                                                     
			timestamp = transcript_payload.get('timestamp')
			if not isinstance(timestamp, int):
				timestamp = int(time.time() * 1000)
			partial_text = transcript_payload.get('text', '').strip()
			if partial_text:
				print(f'[WS] Buffering partial transcript: {partial_text[:60]}...')
				await transcript_buffer_service.add_partial_transcript(
				 meeting_id,
				 text=partial_text,
				 timestamp=timestamp,
				)

	try:
		await deepgram_service.start_session(meeting_id, handle_transcript)
		stt_started = True
		logger.info('Deepgram session started for meeting %s', meeting_id)
	except RuntimeError as exc:
		logger.error('Could not start Deepgram session for meeting %s: %s', meeting_id, exc)
		await websocket.close(code=1013, reason='Deepgram session unavailable')
		return
	except Exception as exc:
		logger.error('Unexpected Deepgram start failure for meeting %s: %s', meeting_id, exc, exc_info=True)
		await websocket.close(code=1011, reason='Deepgram initialization failed')
		return

	try:
		while True:
                                
			message_text = await websocket.receive_text()

			if message_text == 'ping':
				continue

                       
			payload: dict[str, Any]
			try:
				payload = json.loads(message_text)
			except json.JSONDecodeError as err:
				logger.warning(f'WS malformed JSON for meeting {meeting_id}: {err}')
				continue

                   
			timestamp = payload.get('timestamp')
			if timestamp is None:
				logger.warning(f'WS missing timestamp for meeting {meeting_id}')
				continue

			audio_chunk = payload.get('audio_chunk')
			caption_text = payload.get('caption_text', '')
			speaker_name = payload.get('speaker_name', 'Unknown')

                             
			if caption_text:
				logger.info(
				 f'WS ingested | meeting={meeting_id} uid={uid} '
				 f'speaker={speaker_name} caption={caption_text[:50]} '
				 f'timestamp={timestamp} audio={"present" if audio_chunk else "absent"}'
				)

			if audio_chunk:
				try:
					chunk_bytes = base64.b64decode(audio_chunk, validate=True)
				except (binascii.Error, TypeError) as err:
					logger.warning('Invalid audio chunk received for meeting %s: %s', meeting_id, err)
					continue

				if not chunk_bytes:
					continue


				try:
					await deepgram_service.send_audio_chunk(meeting_id, chunk_bytes)
				except Exception as exc:
					logger.error('Failed to forward audio to Deepgram for meeting %s: %s', meeting_id, exc)

	except WebSocketDisconnect:
		logger.info(f'✓ WS disconnected: meeting={meeting_id} uid={uid}')
	except Exception as exc:
		logger.error(f'✗ WS error for meeting {meeting_id}: {type(exc).__name__}: {exc}', exc_info=True)
	finally:
		print(f'\n\n=== MEETING {meeting_id} SHUTDOWN ===')
		try:
			recent_entries = await transcript_buffer_service.get_recent_entries(meeting_id)
			full_entries = await transcript_buffer_service.get_full_entries(meeting_id)
		except Exception:
			recent_entries = []
			full_entries = []

		analysis_entries = recent_entries if recent_entries else full_entries
		print(f'[MEETING] Recent entries={len(recent_entries)} full entries={len(full_entries)} (using {len(analysis_entries)} for Gemini)')
		logger.info('Preparing to run Gemini analysis for meeting %s (entries=%d)', meeting_id, len(analysis_entries))
		analysis_summary = None
		analysis_tasks = []
		try:
			analysis = await gemini_task_service.analyze_meeting(meeting_id, analysis_entries)
		except Exception as exc:
			logger.warning('Gemini final analysis failed for meeting %s: %s', meeting_id, exc)
			print(f'[ERROR] Gemini analysis exception: {exc}')
			analysis = None
		if analysis:
			analysis_summary = analysis.get('summary') or None
			analysis_tasks = analysis.get('tasks') or []
			logger.info('Gemini analysis completed for meeting %s (%d tasks)', meeting_id, len(analysis_tasks))
			print(f'[GEMINI] Analysis completed: {len(analysis_tasks)} tasks')
		else:
			logger.info('Gemini analysis produced no output for meeting %s', meeting_id)
			print(f'[GEMINI] No analysis output')

		transcript_source = full_entries if full_entries else recent_entries
		if transcript_source:
			transcript_text = ' '.join(entry.text for entry in transcript_source)
			logger.info('Meeting %s transcript (%d entries): %s', meeting_id, len(transcript_source), transcript_text)
			print(f'\n=== TRANSCRIPT ({len(transcript_source)} entries) ===')
			print(transcript_text)
		else:
			logger.info('Meeting %s transcript unavailable (no final entries)', meeting_id)
			print('\n=== TRANSCRIPT ===')
			print('(no final transcripts captured)')

		if analysis_summary:
			logger.info('Meeting %s Gemini summary: %s', meeting_id, analysis_summary)
			print(f'\n=== GEMINI SUMMARY ===')
			print(analysis_summary)
		else:
			logger.info('Meeting %s Gemini summary unavailable', meeting_id)
			print('\n=== GEMINI SUMMARY ===')
			print('(no summary generated)')

		if analysis_tasks:
			logger.info('Meeting %s action items (%d):', meeting_id, len(analysis_tasks))
			print(f'\n=== ACTION ITEMS ({len(analysis_tasks)}) ===')
			for idx, task in enumerate(analysis_tasks, start=1):
				logger.info(
				 '  %d. [%s] %s | assignee=%s deadline=%s confidence=%.2f | source="%s"',
				 idx,
				 task.get('priority', 'medium'),
				 task.get('task', ''),
				 task.get('assignee', 'unspecified'),
				 task.get('deadline') or 'unspecified',
				 task.get('confidence', 0.0),
				 task.get('source_text', ''),
				)
				print(f'{idx}. [{task.get("priority", "medium").upper()}] {task.get("task", "")}')
				print(f'   Assignee: {task.get("assignee", "unspecified")}')
				print(f'   Deadline: {task.get("deadline") or "unspecified"}')
				print(f'   Confidence: {task.get("confidence", 0.0):.2f}')
				print(f'   Source: {task.get("source_text", "")}')
				print()
		else:
			logger.info('Meeting %s action items: none detected', meeting_id)
			print('\n=== ACTION ITEMS ===')
			print('(none detected)')

		print(f'=== END MEETING {meeting_id} ===\n')

		if stt_started:
			await deepgram_service.close_session(meeting_id)
			logger.info('Deepgram session closed for meeting %s', meeting_id)
		await transcript_buffer_service.clear_meeting(meeting_id)
		await gemini_task_service.clear_meeting(meeting_id)

               
		if websocket.client_state == WebSocketState.CONNECTED:
			try:
				await websocket.close(code=1000, reason='Server closing')
			except Exception as exc:
				logger.debug(f'Error closing WebSocket: {exc}')
