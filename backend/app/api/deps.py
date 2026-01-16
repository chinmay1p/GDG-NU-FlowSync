from fastapi import Header, HTTPException, status

from app.services.extension_session_service import extension_session_service


async def get_extension_session_context(
 x_extension_session: str | None = Header(default=None, alias='X-Extension-Session'),
):
	"""Authenticate extension requests using the opaque session token."""
	session_id = (x_extension_session or '').strip()
	if not session_id:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing extension session')

	return await extension_session_service.verify_session(session_id)
