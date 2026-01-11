import { authedRequest } from './orgApi'

const buildQueryString = (params = {}) => {
	const query = new URLSearchParams()
	Object.entries(params).forEach(([key, value]) => {
		if (value === undefined || value === null || value === '') {
			return
		}
		query.append(key, value)
	})
	const serialized = query.toString()
	return serialized ? `?${serialized}` : ''
}

export const fetchTasks = async (params = {}) => {
	const query = buildQueryString(params)
	return authedRequest(`/tasks${query}`)
}

export const createTask = async (payload) => {
	return authedRequest('/tasks/create', {
		method: 'POST',
		body: JSON.stringify(payload),
	})
}

export const completeTask = async (taskId) => {
	if (!taskId) {
		throw new Error('taskId is required')
	}
	return authedRequest(`/tasks/${taskId}/complete`, {
		method: 'POST',
	})
}

/**
 * Approve an AI-detected task candidate (managers only)
 * @param {string} pendingId - The pending approval ID
 * @param {number} taskIndex - Index of the task in candidates array
 * @param {object} edits - Optional edits to apply to the task
 * @param {boolean} createGithubIssue - Whether to create a GitHub issue
 */
export const approveTask = async (pendingId, taskIndex, edits = null, createGithubIssue = false) => {
	return authedRequest('/tasks/approve', {
		method: 'POST',
		body: JSON.stringify({
			pendingId,
			taskIndex,
			edits,
			createGithubIssue,
		}),
	})
}

export const approveTasksBatch = async (pendingId, edits = [], createGithubIssue = false) => {
	return authedRequest('/tasks/approve/batch', {
		method: 'POST',
		body: JSON.stringify({
			pendingId,
			edits,
			createGithubIssue,
		}),
	})
}

/**
 * Reject an AI-detected task candidate (managers only)
 * @param {string} pendingId - The pending approval ID
 * @param {number} taskIndex - Index of the task in candidates array
 * @param {string} reason - Optional rejection reason
 */
export const rejectTask = async (pendingId, taskIndex, reason = null) => {
	return authedRequest('/tasks/reject', {
		method: 'POST',
		body: JSON.stringify({
			pendingId,
			taskIndex,
			reason,
		}),
	})
}

export const rejectTasksBatch = async (pendingId, taskIndexes = null, reason = null) => {
	return authedRequest('/tasks/reject/batch', {
		method: 'POST',
		body: JSON.stringify({
			pendingId,
			taskIndexes,
			reason,
		}),
	})
}

/**
 * Get all pending task approvals for the current manager
 */
export const fetchPendingApprovals = async () => {
	return authedRequest('/tasks/pending')
}