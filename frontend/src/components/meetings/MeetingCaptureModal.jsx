/**
 * MeetingCaptureModal - Universal audio capture modal
 * 
 * This modal can:
 * - Capture audio from any source (tab, window, microphone)
 * - Use an existing meeting (Zoom) OR create a new "External Meeting"
 * - Store transcripts and generate summaries for the meeting
 */

import { useState, useEffect, useCallback } from 'react';
import { useUniversalCapture } from '../../hooks/useUniversalCapture';
import { authedRequest } from '../../services/orgApi';

const MeetingCaptureModal = ({
    meeting,  // If provided, capture for this existing meeting
    isOpen,
    onClose,
    onMeetingCreated,
    onTaskDetected,
    teams = []
}) => {
    const {
        isCapturing,
        isStarting,
        error,
        transcripts,
        stats,
        startCapture,
        stopCapture,
        clearTranscripts
    } = useUniversalCapture({ onTaskDetected });

    const [captureMode, setCaptureMode] = useState('tab'); // 'tab' | 'microphone'
    const [showTranscripts, setShowTranscripts] = useState(true);
    const [meetingTitle, setMeetingTitle] = useState('');
    const [selectedTeamId, setSelectedTeamId] = useState('');
    const [currentMeetingId, setCurrentMeetingId] = useState(null);
    const [isCreatingMeeting, setIsCreatingMeeting] = useState(false);
    const [currentMeetingInfo, setCurrentMeetingInfo] = useState(null);

    // Determine if we're capturing for an existing meeting
    const isExistingMeeting = meeting && meeting.meetingId;

    // Reset state when modal opens
    useEffect(() => {
        if (isOpen) {
            if (isExistingMeeting) {
                // Use existing meeting info
                setMeetingTitle(meeting.topic || meeting.title || 'Meeting');
                setSelectedTeamId(meeting.teamId || teams[0]?.teamId || '');
                setCurrentMeetingId(meeting.meetingId);
                setCurrentMeetingInfo({
                    meetingId: meeting.meetingId,
                    title: meeting.topic || meeting.title || 'Meeting',
                    source: meeting.zoomMeetingId ? 'ZOOM' : 'EXTERNAL',
                });
            } else {
                // New meeting - reset
                setMeetingTitle('');
                setSelectedTeamId(teams[0]?.teamId || '');
                setCurrentMeetingId(null);
                setCurrentMeetingInfo(null);
            }
        }
    }, [isOpen, meeting, isExistingMeeting, teams]);

    // Auto-generate meeting title based on date (only for new meetings)
    useEffect(() => {
        if (isOpen && !meetingTitle && !isExistingMeeting) {
            const now = new Date();
            setMeetingTitle(`Meeting ${now.toLocaleDateString()} ${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
        }
    }, [isOpen, meetingTitle, isExistingMeeting]);

    // Close modal when unmounting
    useEffect(() => {
        return () => {
            if (isCapturing) {
                stopCapture();
            }
        };
    }, [isCapturing, stopCapture]);

    /**
     * Create an external meeting in the backend (only for new meetings)
     */
    const createExternalMeeting = useCallback(async () => {
        if (!selectedTeamId || !meetingTitle.trim()) {
            throw new Error('Please select a team and enter a meeting title');
        }

        setIsCreatingMeeting(true);
        try {
            // Create a meeting via the meetings/start endpoint
            const response = await authedRequest('/meetings/start', {
                method: 'POST',
                body: JSON.stringify({
                    teamId: selectedTeamId,
                    title: meetingTitle.trim(),
                    meetingUrl: null, // External meeting - no URL
                }),
            });

            console.log('[Capture] External meeting created:', response);
            setCurrentMeetingId(response.meetingId);
            setCurrentMeetingInfo({
                meetingId: response.meetingId,
                title: meetingTitle.trim(),
                source: 'EXTERNAL',
            });

            if (onMeetingCreated) {
                onMeetingCreated();
            }

            return response.meetingId;
        } finally {
            setIsCreatingMeeting(false);
        }
    }, [selectedTeamId, meetingTitle, onMeetingCreated]);

    /**
     * Activate an existing meeting for capture
     */
    const activateExistingMeeting = useCallback(async () => {
        if (!meeting?.meetingId) {
            throw new Error('No meeting ID provided');
        }

        console.log('[Capture] Using existing meeting:', meeting.meetingId);

        // For existing Zoom meetings, we may need to mark them as active
        // The meeting should already exist in Firestore
        setCurrentMeetingId(meeting.meetingId);

        return meeting.meetingId;
    }, [meeting]);

    const handleStartCapture = async () => {
        try {
            let meetingId;

            if (isExistingMeeting) {
                // Use existing meeting
                meetingId = await activateExistingMeeting();
            } else {
                // Create new external meeting
                meetingId = await createExternalMeeting();
            }

            // Start capture with the meeting ID
            await startCapture({
                meetingId,
                microphoneOnly: captureMode === 'microphone'
            });
        } catch (err) {
            console.error("Capture start error:", err);
        }
    };

    const handleStopCapture = async () => {
        if (currentMeetingId) {
            try {
                // End the meeting and generate summary
                await authedRequest(`/meetings/${currentMeetingId}/end`, {
                    method: 'POST',
                    body: JSON.stringify({ generateSummary: true }),
                });
                console.log('[Capture] Meeting ended, summary generation triggered');

                if (onMeetingCreated) {
                    onMeetingCreated();
                }
            } catch (err) {
                console.error('[Capture] Failed to end meeting:', err);
            }
        }
        await stopCapture();
    };

    const handleClose = async () => {
        if (isCapturing) {
            await handleStopCapture();
        }
        clearTranscripts();
        setCurrentMeetingId(null);
        setCurrentMeetingInfo(null);
        onClose();
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className="w-full max-w-2xl mx-4 bg-white dark:bg-slate-900 rounded-2xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
                {/* Header */}
                <div className={`px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex-shrink-0 ${isExistingMeeting
                        ? 'bg-gradient-to-r from-emerald-500 to-teal-600'
                        : 'bg-gradient-to-r from-indigo-500 to-purple-600'
                    }`}>
                    <div className="flex items-center justify-between">
                        <div>
                            <h2 className="text-xl font-bold text-white">
                                {isExistingMeeting ? '🎙️ Capture Meeting Audio' : '🎙️ New Capture Session'}
                            </h2>
                            <p className="text-sm text-white/80 mt-1">
                                {isExistingMeeting
                                    ? `Recording for: ${meeting.topic || meeting.title || 'Meeting'}`
                                    : 'Capture audio from any meeting or conversation'}
                            </p>
                        </div>
                        <button
                            onClick={handleClose}
                            className="text-white/80 hover:text-white text-2xl font-light"
                        >
                            ×
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div className="p-6 space-y-6 overflow-y-auto flex-1">
                    {/* Capture Controls */}
                    {!isCapturing ? (
                        <div className="space-y-5">
                            {/* Meeting Info Section - Only show for new meetings */}
                            {!isExistingMeeting && (
                                <div className="p-4 bg-slate-50 dark:bg-slate-800 rounded-xl space-y-4">
                                    <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                                        Meeting Details
                                    </h3>

                                    {/* Meeting Title */}
                                    <div>
                                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                                            Meeting Title
                                        </label>
                                        <input
                                            type="text"
                                            value={meetingTitle}
                                            onChange={(e) => setMeetingTitle(e.target.value)}
                                            placeholder="Enter meeting title..."
                                            className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                        />
                                    </div>

                                    {/* Team Selection */}
                                    <div>
                                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                                            Team
                                        </label>
                                        <select
                                            value={selectedTeamId}
                                            onChange={(e) => setSelectedTeamId(e.target.value)}
                                            className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                        >
                                            {teams.length === 0 && (
                                                <option value="">No teams available</option>
                                            )}
                                            {teams.map((team) => (
                                                <option key={team.teamId} value={team.teamId}>
                                                    {team.teamName}
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                            )}

                            {/* Show existing meeting info */}
                            {isExistingMeeting && (
                                <div className="p-4 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl">
                                    <div className="flex items-center gap-3">
                                        <div className="text-2xl">📹</div>
                                        <div>
                                            <p className="font-semibold text-emerald-800 dark:text-emerald-200">
                                                {meeting.topic || meeting.title || 'Meeting'}
                                            </p>
                                            <p className="text-xs text-emerald-600 dark:text-emerald-400">
                                                {meeting.zoomMeetingId ? `Zoom ID: ${meeting.zoomMeetingId}` : 'External Meeting'}
                                                {meeting.teamId && ` • Team: ${meeting.teamId}`}
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Audio Source Selection */}
                            <div>
                                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
                                    Select Audio Source
                                </label>
                                <div className="grid grid-cols-2 gap-3">
                                    <button
                                        onClick={() => setCaptureMode('tab')}
                                        className={`p-4 rounded-xl border-2 text-left transition-all ${captureMode === 'tab'
                                                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30'
                                                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                                            }`}
                                    >
                                        <div className="text-2xl mb-2">🖥️</div>
                                        <div className="font-semibold text-slate-900 dark:text-white">
                                            Tab / Window
                                        </div>
                                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                            Capture from Zoom, Meet, Teams, or any browser tab
                                        </div>
                                    </button>
                                    <button
                                        onClick={() => setCaptureMode('microphone')}
                                        className={`p-4 rounded-xl border-2 text-left transition-all ${captureMode === 'microphone'
                                                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30'
                                                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                                            }`}
                                    >
                                        <div className="text-2xl mb-2">🎤</div>
                                        <div className="font-semibold text-slate-900 dark:text-white">
                                            Microphone
                                        </div>
                                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                            Capture from your microphone (in-person meetings)
                                        </div>
                                    </button>
                                </div>
                            </div>

                            {/* Instructions */}
                            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4">
                                <div className="flex gap-3">
                                    <div className="text-amber-500 text-xl">💡</div>
                                    <div>
                                        <p className="text-sm text-amber-800 dark:text-amber-200 font-medium">
                                            {captureMode === 'tab'
                                                ? 'Share the tab where your meeting is running. Make sure to check "Share tab audio" or "Share system audio" when prompted.'
                                                : 'Make sure your microphone is enabled and has permission to capture audio.'}
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {/* Error Display */}
                            {error && (
                                <div className="bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded-xl p-4">
                                    <p className="text-sm text-rose-700 dark:text-rose-300">
                                        ⚠️ {error}
                                    </p>
                                </div>
                            )}

                            {/* Start Button */}
                            <button
                                onClick={handleStartCapture}
                                disabled={isStarting || isCreatingMeeting || (!isExistingMeeting && (!selectedTeamId || !meetingTitle.trim()))}
                                className={`w-full py-4 px-6 text-white font-bold rounded-xl shadow-lg hover:shadow-xl transition-all disabled:opacity-60 disabled:cursor-not-allowed ${isExistingMeeting
                                        ? 'bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700'
                                        : 'bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700'
                                    }`}
                            >
                                {isStarting || isCreatingMeeting ? (
                                    <span className="flex items-center justify-center gap-2">
                                        <span className="animate-spin">⏳</span>
                                        {isCreatingMeeting ? 'Creating Meeting...' : 'Starting Capture...'}
                                    </span>
                                ) : (
                                    <span className="flex items-center justify-center gap-2">
                                        <span>▶️</span>
                                        Start Capture
                                    </span>
                                )}
                            </button>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {/* Active Capture Status */}
                            <div className="flex items-center justify-between p-4 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl">
                                <div className="flex items-center gap-3">
                                    <div className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
                                    <div>
                                        <p className="font-semibold text-emerald-800 dark:text-emerald-200">
                                            🔴 Recording: {currentMeetingInfo?.title || meetingTitle || 'Capture Session'}
                                        </p>
                                        <p className="text-xs text-emerald-600 dark:text-emerald-400">
                                            {stats.bufferSize || 0} segments • Deepgram {stats.deepgramConnected ? '✓ connected' : 'connecting...'}
                                        </p>
                                    </div>
                                </div>
                                <button
                                    onClick={handleStopCapture}
                                    className="px-4 py-2 bg-rose-500 hover:bg-rose-600 text-white font-semibold rounded-lg transition-colors"
                                >
                                    ⏹️ Stop & Save
                                </button>
                            </div>

                            {/* Live Transcripts */}
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <label className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                                        Live Transcripts
                                    </label>
                                    <button
                                        onClick={() => setShowTranscripts(!showTranscripts)}
                                        className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                                    >
                                        {showTranscripts ? 'Hide' : 'Show'}
                                    </button>
                                </div>
                                {showTranscripts && (
                                    <div className="h-48 overflow-y-auto bg-slate-50 dark:bg-slate-800 rounded-xl p-4 text-sm text-slate-700 dark:text-slate-300 space-y-2">
                                        {transcripts.length === 0 ? (
                                            <p className="text-slate-400 italic">
                                                Listening for speech...
                                            </p>
                                        ) : (
                                            transcripts.map((t, i) => (
                                                <p key={i} className="leading-relaxed">
                                                    {t.text}
                                                </p>
                                            ))
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Task Detection Info */}
                            <div className="bg-slate-50 dark:bg-slate-800 rounded-xl p-4">
                                <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                                    <span className="text-lg">🤖</span>
                                    <span>
                                        Gemini is analyzing speech for task candidates...
                                        {stats.canCallGemini
                                            ? ' (Ready to analyze)'
                                            : ` (Next analysis in ${stats.timeUntilNextCall || 0}s)`}
                                    </span>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 flex-shrink-0">
                    <p className="text-xs text-slate-500 dark:text-slate-400 text-center">
                        🔐 Audio is processed via Deepgram STT. Transcripts and summaries are saved to this meeting.
                        {currentMeetingId && (
                            <span className="block mt-1 text-indigo-600 dark:text-indigo-400">
                                Meeting ID: {currentMeetingId}
                            </span>
                        )}
                    </p>
                </div>
            </div>
        </div>
    );
};

export default MeetingCaptureModal;
