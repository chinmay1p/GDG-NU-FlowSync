import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.services.extension_session_service import extension_session_service
from app.services.websocket_manager import websocket_manager
from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)


class TaskDetectionService:

    COLLECTION_NAME = 'meeting_session_triggers'
    EVENT_NAME = 'TASK_DETECTED'

                                                                           
    def __init__(self) -> None:
        ensure_firebase_initialized()

                                                                 
    async def start_session(self, session_token: str, meeting_source: str) -> Dict:
        token = (session_token or '').strip()
        if not token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='sessionToken is required')

        session_context = await extension_session_service.verify_session(token)
        token_hash = self._hash_token(token)
        logger.info('Meeting session start requested: token=%s uid=%s', token_hash[:16], session_context.get('uid'))

        already_triggered = await asyncio.to_thread(self._session_already_triggered, token_hash)
        if already_triggered:
            logger.info('Replaying detection for token %s', token_hash[:16])
            asyncio.create_task(self._emit_detection_after_delay(token_hash, session_context))
            return {'status': 'replayed', 'triggerId': token_hash}

        await asyncio.to_thread(self._mark_triggered, token_hash, session_context, meeting_source)

        asyncio.create_task(self._emit_detection_after_delay(token_hash, session_context))

        return {'status': 'queued', 'triggerId': token_hash}

                                                             
    async def _emit_detection_after_delay(self, trigger_id: str, session_context: Dict) -> None:
        logger.info('Scheduled detection emission in 10s for trigger %s', trigger_id[:16])
        await asyncio.sleep(10)

        payload = {
            'triggerId': trigger_id,
            'title': 'Fix login bug',
            'description': 'Discussed during Google Meet',
            'assignedToEmail': 'shahayush091@gmail.com',
            'priority': 'HIGH',
            'source': 'MEETING_AI',
            'orgId': session_context.get('orgId'),
        }

        user_id = session_context.get('uid')
        if not user_id:
            logger.warning('Cannot emit task detection: missing uid for trigger %s', trigger_id)
            return

        logger.info('Emitting TASK_DETECTED to user %s', user_id)
        try:
            await websocket_manager.emit_to_user(user_id, self.EVENT_NAME, payload)
            logger.info('Emitted %s event for user %s (trigger=%s)', self.EVENT_NAME, user_id, trigger_id)
        except Exception as exc:
            logger.warning('Failed to emit detection event for %s: %s', user_id, exc)

                                                          
    def _session_already_triggered(self, token_hash: str) -> bool:
        client = self._get_client()
        snapshot = client.collection(self.COLLECTION_NAME).document(token_hash).get()
        return snapshot.exists

                                                
    def _mark_triggered(self, token_hash: str, session_context: Dict, meeting_source: str) -> None:
        client = self._get_client()
        doc = client.collection(self.COLLECTION_NAME).document(token_hash)
        doc.set(
            {
                'triggerId': token_hash,
                'uid': session_context.get('uid'),
                'email': session_context.get('email'),
                'orgId': session_context.get('orgId'),
                'meetingSource': meeting_source,
                'triggeredAt': datetime.now(tz=timezone.utc),
            }
        )

                                         
    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

                                            
    @staticmethod
    def _get_client():
        ensure_firebase_initialized()
        return firestore.client()


task_detection_service = TaskDetectionService()
