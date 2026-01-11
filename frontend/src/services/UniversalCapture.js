/**
 * UniversalCapture - Universal audio capture service with STT and task detection
 * 
 * Clean public API for integration into any app:
 * - startCapture(options) - Start audio capture
 * - stopCapture() - Stop audio capture
 * - onTranscript(callback) - Register transcript callback
 * - onTaskDetected(callback) - Register task detection callback
 * - isCapturing() - Check if capture is active
 * 
 * This module provides live audio capture from any source (tab, window, system)
 * with speech-to-text via Deepgram and task detection via Gemini.
 */

import { transcriptBuffer } from './TranscriptBuffer';
import { authedRequest } from './orgApi';

// Deepgram API key
const DEEPGRAM_API_KEY = import.meta.env.VITE_DEEPGRAM_API_KEY;

// Capture state
let mediaStream = null;
let audioContext = null;
let deepgramSocket = null;
let isCapturingAudio = false;
let transcriptCallbacks = [];
let taskCallbacks = [];
let currentMeetingId = null;
let transcriptSegmentIndex = 0;
let geminiCallInProgress = false; // Prevent concurrent Gemini calls

/**
 * Save transcript segment to the backend
 */
const saveTranscriptToBackend = async (text, timestamp) => {
    if (!currentMeetingId) {
        console.log("[UniversalCapture] No meeting ID, skipping transcript save");
        return;
    }

    try {
        await authedRequest(`/meetings/${currentMeetingId}/transcript`, {
            method: 'POST',
            body: JSON.stringify({
                text,
                timestamp,
                speaker: 'Unknown', // Could be enhanced with speaker diarization
                segmentIndex: transcriptSegmentIndex++,
            }),
        });
        console.log("[UniversalCapture] Transcript saved to meeting");
    } catch (err) {
        console.warn("[UniversalCapture] Failed to save transcript:", err.message);
    }
};

/**
 * Send detected tasks to the backend for approval
 * This triggers TASK_DETECTED WebSocket events to managers
 */
const sendTasksToBackend = async (tasks, summary) => {
    if (!currentMeetingId) {
        console.log("[UniversalCapture] No meeting ID, skipping task submission");
        return;
    }

    if (!tasks || tasks.length === 0) {
        return;
    }

    try {
        const response = await authedRequest(`/meetings/${currentMeetingId}/tasks`, {
            method: 'POST',
            body: JSON.stringify({
                tasks: tasks.map(t => ({
                    title: t.title || 'Untitled Task',
                    description: t.description || '',
                    assignee: t.assignee || '',
                    priority: t.priority || 'medium',
                    deadline: t.deadline || null,
                    confidence: t.confidence || 0.5,
                })),
                summary: summary || null,
            }),
        });
        console.log("[UniversalCapture] Tasks submitted to backend:", response);
    } catch (err) {
        console.warn("[UniversalCapture] Failed to submit tasks:", err.message);
    }
};

/**
 * Convert Float32Array to Int16Array for Deepgram
 */
const float32ToInt16 = (float32Array) => {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const clamped = Math.max(-1, Math.min(1, float32Array[i]));
        int16Array[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
    }
    return int16Array;
};

/**
 * Connect to Deepgram WebSocket for real-time STT
 */
const connectToDeepgram = () => {
    if (!DEEPGRAM_API_KEY) {
        console.error("[UniversalCapture] DEEPGRAM_API_KEY is not set");
        return null;
    }

    const params = new URLSearchParams({
        encoding: "linear16",
        sample_rate: "48000",
        channels: "1",
        punctuate: "true",
        interim_results: "true",
        endpointing: "300"
    });

    const url = `wss://api.deepgram.com/v1/listen?${params.toString()}`;
    console.log("[UniversalCapture] Connecting to Deepgram...");

    const socket = new WebSocket(url, ["token", DEEPGRAM_API_KEY]);

    socket.onopen = () => {
        console.log("[UniversalCapture] Deepgram connected");
    };

    socket.onmessage = async (event) => {
        try {
            const data = JSON.parse(event.data);
            const transcript = data?.channel?.alternatives?.[0]?.transcript || "";
            const isFinal = data?.is_final || false;

            if (transcript && isFinal) {
                console.log(`[UniversalCapture] Transcript: ${transcript}`);

                const timestamp = Date.now();

                // Save transcript to backend
                saveTranscriptToBackend(transcript, timestamp);

                // Notify all transcript callbacks
                transcriptCallbacks.forEach(cb => {
                    try {
                        cb({ text: transcript, timestamp, isFinal });
                    } catch (err) {
                        console.error("[UniversalCapture] Transcript callback error:", err);
                    }
                });

                // Add to buffer and check for task detection
                transcriptBuffer.addTranscript(transcript);

                // Try calling Gemini for task extraction (with lock to prevent concurrent calls)
                if (!geminiCallInProgress) {
                    geminiCallInProgress = true;
                    try {
                        const result = await transcriptBuffer.tryCallGemini();
                        if (result?.tasks?.length > 0) {
                            console.log("[UniversalCapture] Tasks detected:", result.tasks);

                            // Send tasks to backend for manager approval (triggers TASK_DETECTED WebSocket)
                            await sendTasksToBackend(result.tasks, result.summary);

                            // Notify all task callbacks
                            taskCallbacks.forEach(cb => {
                                try {
                                    cb({
                                        tasks: result.tasks,
                                        summary: result.summary,
                                        meetingId: currentMeetingId,
                                        timestamp: Date.now()
                                    });
                                } catch (err) {
                                    console.error("[UniversalCapture] Task callback error:", err);
                                }
                            });
                        }
                    } finally {
                        geminiCallInProgress = false;
                    }
                }
            }
        } catch (err) {
            console.error("[UniversalCapture] Deepgram message parse error:", err);
        }
    };

    socket.onerror = (err) => {
        console.error("[UniversalCapture] Deepgram error:", err);
    };

    socket.onclose = () => {
        console.log("[UniversalCapture] Deepgram disconnected");
    };

    return socket;
};

/**
 * Request audio stream from user
 * @param {Object} options - Capture options
 * @param {boolean} options.systemAudio - Request system audio (requires video track)
 * @param {boolean} options.microphoneOnly - Use microphone instead of display media
 * @returns {Promise<MediaStream>}
 */
const requestAudioStream = async (options = {}) => {
    const { microphoneOnly = false } = options;

    if (microphoneOnly) {
        // Use microphone directly
        console.log("[UniversalCapture] Requesting microphone access...");
        return navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                sampleRate: 48000
            },
            video: false
        });
    }

    // Use getDisplayMedia for tab/window/system audio
    console.log("[UniversalCapture] Requesting display media (tab/window/system audio)...");

    try {
        // Try audio-only first (some browsers support this)
        return await navigator.mediaDevices.getDisplayMedia({
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                sampleRate: 48000
            },
            video: false
        });
    } catch (err) {
        // Fallback: require video but we'll only use audio
        console.log("[UniversalCapture] Audio-only not supported, requesting with video...");
        return await navigator.mediaDevices.getDisplayMedia({
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                sampleRate: 48000
            },
            video: {
                frameRate: 1,
                width: 1,
                height: 1
            }
        });
    }
};

/**
 * Start universal audio capture
 * @param {Object} options - Capture options
 * @param {string} options.meetingId - Optional meeting ID to associate with
 * @param {boolean} options.microphoneOnly - Use microphone instead of display media
 * @returns {Promise<void>}
 */
export const startCapture = async (options = {}) => {
    if (isCapturingAudio) {
        console.warn("[UniversalCapture] Capture already running");
        return;
    }

    const { meetingId = null, microphoneOnly = false } = options;
    currentMeetingId = meetingId;
    transcriptSegmentIndex = 0;

    console.log(`[UniversalCapture] Starting capture...${meetingId ? ` (Meeting: ${meetingId})` : ''}`);

    try {
        // Request audio stream
        mediaStream = await requestAudioStream({ microphoneOnly });

        const audioTracks = mediaStream.getAudioTracks();
        if (audioTracks.length === 0) {
            throw new Error("No audio track available. Make sure to check 'Share tab audio' or 'Share system audio' when selecting.");
        }

        console.log("[UniversalCapture] Audio track:", audioTracks[0].label);

        // Connect to Deepgram
        deepgramSocket = connectToDeepgram();
        if (!deepgramSocket) {
            throw new Error("Failed to connect to Deepgram STT service");
        }

        // Create AudioContext
        audioContext = new AudioContext({ sampleRate: 48000 });
        const source = audioContext.createMediaStreamSource(mediaStream);
        const bufferSize = 4096;
        const scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);

        scriptProcessor.onaudioprocess = (event) => {
            const inputData = event.inputBuffer.getChannelData(0);

            // Send to Deepgram
            if (deepgramSocket?.readyState === WebSocket.OPEN) {
                const int16Data = float32ToInt16(inputData);
                deepgramSocket.send(int16Data.buffer);
            }
        };

        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        isCapturingAudio = true;
        console.log("[UniversalCapture] ✓ Capture started successfully");

        // Handle stream end (user stops sharing)
        const tracks = mediaStream.getTracks();
        tracks.forEach(track => {
            track.onended = () => {
                console.log("[UniversalCapture] Stream ended by user");
                stopCapture();
            };
        });

    } catch (err) {
        console.error("[UniversalCapture] Start failed:", err);
        await stopCapture();
        throw err;
    }
};

/**
 * Stop audio capture
 */
export const stopCapture = async () => {
    console.log("[UniversalCapture] Stopping capture...");
    isCapturingAudio = false;

    // Flush any pending transcripts to Gemini
    try {
        await transcriptBuffer.tryCallGemini();
    } catch (err) {
        console.warn("[UniversalCapture] Failed to flush transcripts:", err);
    }

    // Close Deepgram socket
    if (deepgramSocket?.readyState === WebSocket.OPEN) {
        deepgramSocket.close();
    }
    deepgramSocket = null;

    // Close AudioContext
    if (audioContext) {
        try {
            await audioContext.close();
        } catch (err) {
            // Ignore close errors
        }
    }
    audioContext = null;

    // Stop all tracks
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    mediaStream = null;

    // Clear buffer
    transcriptBuffer.clear();
    currentMeetingId = null;

    console.log("[UniversalCapture] ✓ Capture stopped");
};

/**
 * Register a callback for transcript events
 * @param {Function} callback - Called with { text, timestamp, isFinal }
 * @returns {Function} - Unsubscribe function
 */
export const onTranscript = (callback) => {
    transcriptCallbacks.push(callback);
    return () => {
        transcriptCallbacks = transcriptCallbacks.filter(cb => cb !== callback);
    };
};

/**
 * Register a callback for task detection events
 * @param {Function} callback - Called with { tasks, summary, meetingId, timestamp }
 * @returns {Function} - Unsubscribe function
 */
export const onTaskDetected = (callback) => {
    taskCallbacks.push(callback);
    return () => {
        taskCallbacks = taskCallbacks.filter(cb => cb !== callback);
    };
};

/**
 * Check if capture is currently active
 * @returns {boolean}
 */
export const isCapturing = () => isCapturingAudio;

/**
 * Get current meeting ID
 * @returns {string|null}
 */
export const getCurrentMeetingId = () => currentMeetingId;

/**
 * Get buffer stats for debugging
 * @returns {Object}
 */
export const getStats = () => ({
    isCapturing: isCapturingAudio,
    meetingId: currentMeetingId,
    deepgramConnected: deepgramSocket?.readyState === WebSocket.OPEN,
    ...transcriptBuffer.getStats()
});

// Default export for convenience
export default {
    startCapture,
    stopCapture,
    onTranscript,
    onTaskDetected,
    isCapturing,
    getCurrentMeetingId,
    getStats
};
