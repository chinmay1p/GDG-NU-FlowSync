import logging
import os
import time
from typing import Any

import jwt
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

ZOOM_APP_CLIENT_ID = os.getenv('ZOOM_APP_CLIENT_ID')
ZOOM_APP_CLIENT_SECRET = os.getenv('ZOOM_APP_CLIENT_SECRET')


class ZoomSDKService:

	ALGORITHM = 'HS256'
	TOKEN_TTL_SECONDS = 120

	# Initializes the service with Zoom OAuth credentials from environment.
	def __init__(self) -> None:
		if not ZOOM_APP_CLIENT_ID or not ZOOM_APP_CLIENT_SECRET:
			logger.warning('Zoom SDK environment variables are not configured. Signatures cannot be generated.')
		self._client_id = ZOOM_APP_CLIENT_ID
		self._client_secret = ZOOM_APP_CLIENT_SECRET

	# Generates a JWT signature for Zoom Meeting SDK authentication.
	def generate_signature(self, *, meeting_number: str, role: int) -> str:
		meeting_id = (meeting_number or '').strip()
		if not meeting_id:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='meetingNumber is required')

		if role not in (0, 1):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='role must be 0 or 1')

		issued_at = int(time.time())
		expires_at = issued_at + self.TOKEN_TTL_SECONDS

		payload: dict[str, Any] = {
			'sdkKey': self._client_id,
			'mn': meeting_id,
			'role': role,
			'iat': issued_at,
			'exp': expires_at,
			'appKey': self._client_id,
			'tokenExp': expires_at,
		}

		logger.info('Generating Zoom SDK signature for meeting=%s role=%s exp=%s', meeting_id, role, expires_at)
		return jwt.encode(payload, self._client_secret, algorithm=self.ALGORITHM)


default_zoom_sdk_service = ZoomSDKService()
zoom_sdk_service = default_zoom_sdk_service