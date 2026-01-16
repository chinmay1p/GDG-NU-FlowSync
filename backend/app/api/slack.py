import hmac
import hashlib
import logging
import os
import time
from fastapi import APIRouter, HTTPException, Request, status
from starlette.responses import PlainTextResponse

from app.services.task_service import SlackCommandPayload, task_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/slack', tags=['slack'])

SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')


def _verify_slack_signature(request: Request, body: bytes) -> None:
	if not SLACK_SIGNING_SECRET:
		raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Slack integration is not configured')

	signature = request.headers.get('x-slack-signature')
	timestamp = request.headers.get('x-slack-request-timestamp')
	if not signature or not timestamp:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing Slack signature headers')

	try:
		req_ts = int(timestamp)
	except ValueError:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Slack timestamp')

	if abs(time.time() - req_ts) > 60 * 5:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Stale Slack request')

	basestring = f'v0:{timestamp}:{body.decode()}'
	computed = 'v0=' + hmac.new(
	 SLACK_SIGNING_SECRET.encode(),
	 basestring.encode(),
	 hashlib.sha256,
	).hexdigest()

	if not hmac.compare_digest(computed, signature):
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Slack signature')


@router.post('/command')
async def handle_slack_command(request: Request):
	body = await request.body()
	_verify_slack_signature(request, body)
	form = await request.form()

	command_text = form.get('text', '')
	team_id = form.get('team_id')
	user_id = form.get('user_id')
	user_name = form.get('user_name')
	user_email = form.get('user_email')

	if not team_id:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Missing team id')

	payload = SlackCommandPayload(
	 team_id=team_id,
	 text=command_text or '',
	 slack_user_id=user_id or 'unknown',
	 user_name=user_name or 'unknown',
	 user_email=user_email,
	)

	try:
		task = task_service.create_task_from_slack(payload)
	except HTTPException as exc:
		message = exc.detail or 'Unable to create task.'
		logger.warning('Slack command failed: %s', message)
		return PlainTextResponse(message)
	except Exception as exc:                
		logger.exception('Unexpected Slack command error: %s', exc)
		return PlainTextResponse('Something went wrong while creating the task.')

	if task.get('githubIssueUrl'):
		return PlainTextResponse('Task created successfully and GitHub issue linked.')
	return PlainTextResponse('Task created successfully, but GitHub issue linking failed. Please check GitHub token and repo settings.')

