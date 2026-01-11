import asyncio
import inspect
import json
import logging
import os
import time
from typing import Awaitable, Callable, Dict, Optional

from urllib.parse import urlencode

try:
	from websockets.asyncio.client import connect as ws_connect
except ImportError:
	from websockets.client import connect as ws_connect  # type: ignore

from websockets.exceptions import ConnectionClosed

_WS_CONNECT_SUPPORTS_ADDITIONAL = 'additional_headers' in inspect.signature(ws_connect).parameters
_WS_CONNECT_SUPPORTS_EXTRA = 'extra_headers' in inspect.signature(ws_connect).parameters

TranscriptCallback = Callable[[dict], Awaitable[None]]

logger = logging.getLogger(__name__)


DEEPGRAM_LISTEN_ENDPOINT = 'wss://api.deepgram.com/v1/listen'


class DeepgramStreamingSession:

	# Initializes a Deepgram streaming session with meeting ID, API key, and callback.
	def __init__(self, meeting_id: str, api_key: str, callback: TranscriptCallback):
		self.meeting_id = meeting_id
		self._api_key = api_key
		self._callback = callback
		self._loop = asyncio.get_running_loop()
		self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=200)
		self._stopping = False
		self._closed = False
		self._worker: Optional[asyncio.Task] = asyncio.create_task(self._run())

	# Returns whether the session is closed.
	@property
	def closed(self) -> bool:
		return self._closed

	# Adds an audio chunk to the queue for transcription.
	async def add_audio(self, chunk: bytes) -> None:
		if self._stopping or self._closed:
			logger.debug('Deepgram session %s ignoring audio: stopping=%s closed=%s', self.meeting_id, self._stopping, self._closed)
			return
		if not chunk:
			return
		try:
			self._audio_queue.put_nowait(chunk)
		except asyncio.QueueFull:
			try:
				self._audio_queue.get_nowait()
			except asyncio.QueueEmpty:
				pass
			self._audio_queue.put_nowait(chunk)

	# Closes the session gracefully.
	async def close(self) -> None:
		if self._stopping:
			return
		self._stopping = True
		try:
			self._audio_queue.put_nowait(None)
		except asyncio.QueueFull:
			try:
				self._audio_queue.get_nowait()
			except asyncio.QueueEmpty:
				pass
			self._audio_queue.put_nowait(None)
		if self._worker:
			try:
				await self._worker
			except Exception as exc:
				logger.error('Deepgram worker shutdown error [%s]: %s', self.meeting_id, exc, exc_info=True)
			finally:
				self._worker = None

	# Main worker loop that runs the transcription.
	async def _run(self) -> None:
		try:
			await self._transcribe()
		except Exception as exc:
			logger.error('Deepgram streaming error [%s]: %s', self.meeting_id, exc, exc_info=True)
		finally:
			self._closed = True

	# Connects to Deepgram and manages send/receive loops.
	async def _transcribe(self) -> None:
		params = urlencode(
			{
				'model': 'nova-2',
				'encoding': 'linear16',
				'sample_rate': 16000,
				'channels': 1,
				'language': 'en',
				'interim_results': 'true',
				'smart_format': 'true',
				'punctuate': 'true',
			}
		)
		url = f'{DEEPGRAM_LISTEN_ENDPOINT}?{params}'
		headers = [('Authorization', f'Token {self._api_key}'), ('Accept', 'application/json')]
		connect_kwargs = {}
		if _WS_CONNECT_SUPPORTS_ADDITIONAL:
			connect_kwargs['additional_headers'] = headers
		elif _WS_CONNECT_SUPPORTS_EXTRA:
			connect_kwargs['extra_headers'] = dict(headers)
		else:
			raise RuntimeError('Installed websockets package does not support passing HTTP headers')
		try:
			async with ws_connect(url, **connect_kwargs) as websocket:
				config_msg = {
					'type': 'start',
					'encoding': 'linear16',
					'sample_rate': 16000,
					'channels': 1,
					'language': 'en',
					'interim_results': True,
					'smart_format': True,
					'punctuate': True,
				}
				await websocket.send(json.dumps(config_msg))

				send_task = asyncio.create_task(self._send_audio_loop(websocket))
				receive_task = asyncio.create_task(self._receive_loop(websocket))
				await asyncio.gather(send_task, receive_task)
		except Exception as exc:
			logger.error('Failed to connect to Deepgram for meeting %s: %s', self.meeting_id, exc)

	# Sends audio chunks from the queue to Deepgram.
	async def _send_audio_loop(self, websocket) -> None:
		try:
			while True:
				chunk = await self._audio_queue.get()
				if chunk is None:
					await websocket.send(json.dumps({'type': 'stop'}))
					break
				await websocket.send(chunk)
		except ConnectionClosed:
			logger.warning('Deepgram connection closed while sending audio for meeting %s', self.meeting_id)
		except Exception as exc:
			logger.error('Deepgram audio sender error [%s]: %s', self.meeting_id, exc)

	# Receives transcription results from Deepgram.
	async def _receive_loop(self, websocket) -> None:
		try:
			async for message in websocket:
				if isinstance(message, bytes):
					continue
				payload = json.loads(message)
				await self._handle_deepgram_message(payload)
		except ConnectionClosed:
			logger.info('Deepgram connection closed for meeting %s', self.meeting_id)
		except Exception as exc:
			logger.error('Deepgram message receiver error [%s]: %s', self.meeting_id, exc)

	# Parses a Deepgram message and dispatches transcript callback.
	async def _handle_deepgram_message(self, payload: dict) -> None:
		if payload.get('type') != 'Results':
			return
		channel = payload.get('channel', {})
		alternatives = channel.get('alternatives', [])
		if not alternatives:
			return
		transcript_text = alternatives[0].get('transcript', '').strip()
		if not transcript_text:
			return
		is_final = payload.get('is_final', False)
		confidence = alternatives[0].get('confidence') if is_final else None
		log_level = 'FINAL' if is_final else 'PARTIAL'
		logger.info('[DG %s]: %s', log_level, transcript_text)
		transcript_payload = {
			'type': 'transcript',
			'meeting_id': self.meeting_id,
			'text': transcript_text,
			'is_final': is_final,
			'confidence': confidence,
			'timestamp': int(time.time() * 1000),
		}
		await self._dispatch_callback(transcript_payload)

	# Invokes the transcript callback with error handling.
	async def _dispatch_callback(self, payload: dict) -> None:
		try:
			await self._callback(payload)
		except Exception as exc:
			logger.error('Transcript callback failed for meeting %s: %s', self.meeting_id, exc, exc_info=True)


class DeepgramSTTService:

	# Initializes the service with API key from environment.
	def __init__(self):
		api_key = os.getenv('DEEPGRAM_API_KEY')
		if not api_key:
			raise RuntimeError('DEEPGRAM_API_KEY environment variable not set')
		self._api_key = api_key
		self._sessions: Dict[str, DeepgramStreamingSession] = {}
		self._callbacks: Dict[str, TranscriptCallback] = {}
		self._lock = asyncio.Lock()

	# Starts a new Deepgram session for a meeting.
	async def start_session(self, meeting_id: str, callback: TranscriptCallback) -> DeepgramStreamingSession:
		self._callbacks[meeting_id] = callback
		return await self._create_session(meeting_id, callback)

	# Creates a new session, closing any existing one.
	async def _create_session(self, meeting_id: str, callback: TranscriptCallback) -> DeepgramStreamingSession:
		async with self._lock:
			existing = self._sessions.get(meeting_id)
			if existing:
				if not existing.closed:
					raise RuntimeError(f'Deepgram session already active for meeting {meeting_id}')
				self._sessions.pop(meeting_id, None)
			session = DeepgramStreamingSession(meeting_id, self._api_key, callback)
			self._sessions[meeting_id] = session
			return session

	# Ensures a session exists, recreating if closed.
	async def _ensure_session(self, meeting_id: str) -> DeepgramStreamingSession:
		session = self._sessions.get(meeting_id)
		if session and not session.closed:
			return session
		callback = self._callbacks.get(meeting_id)
		if not callback:
			raise RuntimeError(f'No transcript callback registered for meeting {meeting_id}')
		logger.info('Rehydrating Deepgram session for meeting %s', meeting_id)
		return await self._create_session(meeting_id, callback)

	# Sends an audio chunk to the meeting's session.
	async def send_audio_chunk(self, meeting_id: str, chunk: bytes) -> None:
		session = await self._ensure_session(meeting_id)
		await session.add_audio(chunk)

	# Closes and removes a session for a meeting.
	async def close_session(self, meeting_id: str) -> None:
		async with self._lock:
			session = self._sessions.pop(meeting_id, None)
			self._callbacks.pop(meeting_id, None)
		if session:
			await session.close()

	# Closes all active sessions.
	async def close_all(self) -> None:
		async with self._lock:
			sessions = self._sessions
			self._sessions = {}
			self._callbacks = {}
		for session in sessions.values():
			await session.close()


deepgram_service = DeepgramSTTService()
