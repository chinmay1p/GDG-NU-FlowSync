/**
 * useUniversalCapture - React hook for universal audio capture
 * 
 * Provides a clean React interface for:
 * - Starting/stopping audio capture
 * - Receiving transcripts in real-time
 * - Receiving task detection events
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import * as UniversalCapture from '../services/UniversalCapture';

/**
 * Hook for universal audio capture with STT and task detection
 * @param {Object} options - Hook options
 * @param {Function} options.onTaskDetected - Callback when tasks are detected
 * @returns {Object} - Capture state and controls
 */
export function useUniversalCapture(options = {}) {
    const { onTaskDetected: taskCallback } = options;

    const [isCapturing, setIsCapturing] = useState(false);
    const [isStarting, setIsStarting] = useState(false);
    const [error, setError] = useState(null);
    const [transcripts, setTranscripts] = useState([]);
    const [stats, setStats] = useState({});

    const taskCallbackRef = useRef(taskCallback);
    taskCallbackRef.current = taskCallback;

    // Subscribe to transcript events
    useEffect(() => {
        const unsubTranscript = UniversalCapture.onTranscript((data) => {
            setTranscripts(prev => [...prev.slice(-99), data]); // Keep last 100
        });

        const unsubTask = UniversalCapture.onTaskDetected((data) => {
            console.log("[useUniversalCapture] Tasks detected:", data);
            if (taskCallbackRef.current) {
                taskCallbackRef.current(data);
            }
        });

        // Poll stats
        const statsInterval = setInterval(() => {
            setStats(UniversalCapture.getStats());
            setIsCapturing(UniversalCapture.isCapturing());
        }, 1000);

        return () => {
            unsubTranscript();
            unsubTask();
            clearInterval(statsInterval);
        };
    }, []);

    // Sync state with capture service
    useEffect(() => {
        setIsCapturing(UniversalCapture.isCapturing());
    }, []);

    /**
     * Start audio capture
     * @param {Object} captureOptions - Options for capture
     * @param {string} captureOptions.meetingId - Meeting ID to associate
     * @param {boolean} captureOptions.microphoneOnly - Use mic instead of display media
     */
    const startCapture = useCallback(async (captureOptions = {}) => {
        setError(null);
        setIsStarting(true);
        setTranscripts([]);

        try {
            await UniversalCapture.startCapture(captureOptions);
            setIsCapturing(true);
        } catch (err) {
            console.error("[useUniversalCapture] Start failed:", err);
            setError(err.message || "Failed to start capture");
            throw err;
        } finally {
            setIsStarting(false);
        }
    }, []);

    /**
     * Stop audio capture
     */
    const stopCapture = useCallback(async () => {
        try {
            await UniversalCapture.stopCapture();
        } finally {
            setIsCapturing(false);
        }
    }, []);

    /**
     * Clear all transcripts
     */
    const clearTranscripts = useCallback(() => {
        setTranscripts([]);
    }, []);

    return {
        // State
        isCapturing,
        isStarting,
        error,
        transcripts,
        stats,

        // Actions
        startCapture,
        stopCapture,
        clearTranscripts,
    };
}

export default useUniversalCapture;
