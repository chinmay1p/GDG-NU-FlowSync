import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = 'https://api.github.com'


def create_issue(repo: str, title: str, body: str, token: Optional[str] = None) -> Optional[dict]:
	"""Create a GitHub issue in the provided repo. Returns the issue metadata or None."""
	repo_slug = (repo or '').strip()
	if not repo_slug:
		logger.warning('Cannot create GitHub issue: repo is missing')
		return None

                                                           
	if not token:
		token = os.getenv('GITHUB_TOKEN')
 
	if not token:
		logger.warning('Cannot create GitHub issue: GITHUB_TOKEN is not configured')
		return None

	issue_payload = {
	 'title': title[:240] if title else 'Meeting task',
	 'body': body or 'Task created from Meeting Intelligence platform.',
	}

	headers = {
	 'Authorization': f'Bearer {token}',
	 'Accept': 'application/vnd.github+json',
	 'User-Agent': 'meeting-intelligence-extension',
	}

	url = f'{GITHUB_API_BASE}/repos/{repo_slug}/issues'
	try:
		response = requests.post(url, json=issue_payload, headers=headers, timeout=10)
		response.raise_for_status()
	except requests.RequestException as error:
		logger.error('Failed to create GitHub issue for repo %s: %s', repo_slug, error)
		return None

	data = response.json() or {}
	issue_url = data.get('html_url') or data.get('url')
	issue_number = data.get('number')
	if issue_url:
		logger.info('GitHub issue created: %s', issue_url)
	else:
		logger.warning('GitHub issue created but response missing URL')
	if not issue_url and issue_number is None:
		return None
	return {'url': issue_url, 'number': issue_number}
