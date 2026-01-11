import { authedRequest } from './orgApi'

export const fetchMeetings = async () => {
	return authedRequest('/meetings', { method: 'GET' })
}

export const createMeeting = async ({ teamId, topic, startTime, durationMinutes }) => {
	return authedRequest('/zoom/meeting/create', {
		method: 'POST',
		body: JSON.stringify({ teamId, topic, startTime, durationMinutes }),
	})
}

export const fetchMeetingTranscript = async (meetingId) => {
	if (!meetingId) throw new Error('meetingId is required')
	return authedRequest(`/meetings/${meetingId}/transcript`, { method: 'GET' })
}

export const fetchMeetingSummary = async (meetingId) => {
	if (!meetingId) throw new Error('meetingId is required')
	return authedRequest(`/meetings/${meetingId}/summary`, { method: 'GET' })
}

export const fetchMeetingDetail = async (meetingId) => {
	if (!meetingId) throw new Error('meetingId is required')
	return authedRequest(`/meetings/${meetingId}`, { method: 'GET' })
}

export const deleteMeeting = async (meetingId) => {
	if (!meetingId) throw new Error('meetingId is required')
	return authedRequest(`/meetings/${meetingId}`, { method: 'DELETE' })
}