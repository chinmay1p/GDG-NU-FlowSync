/**
 * ZoomBotClient - Headless Zoom meeting bot that automatically joins and captures audio
 * 
 * This page is designed to be opened via window.open() and runs without user interaction.
 * It will:
 * 1. Fetch meeting details from backend
 * 2. Join the Zoom meeting automatically
 * 3. Start audio capture and stream to Deepgram
 * 4. Close itself when the meeting ends
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { ZoomMtg } from "@zoom/meetingsdk";
import { authedRequest } from "../services/orgApi";
import { transcriptBuffer } from "../services/TranscriptBuffer";
import { auth } from "../config/firebase";

// Zoom SDK setup
const ZOOM_SDK_VERSION = "5.0.4";
ZoomMtg.setZoomJSLib(`https://source.zoom.us/${ZOOM_SDK_VERSION}/lib`, "/av");
ZoomMtg.preLoadWasm();
ZoomMtg.prepareWebSDK();

// Deepgram API key
const DEEPGRAM_API_KEY = import.meta.env.VITE_DEEPGRAM_API_KEY;

const ZoomBotClient = () => {
    const { meetingId } = useParams();
    const [status, setStatus] = useState("Initializing bot...");
    const [isJoined, setIsJoined] = useState(false);
    const [isCapturing, setIsCapturing] = useState(false);

    // Refs for cleanup
    const mediaStreamRef = useRef(null);
    const audioContextRef = useRef(null);
    const deepgramSocketRef = useRef(null);
    const hasInitializedRef = useRef(false);
    const cleanupGuardRef = useRef({ skip: true });

    // Convert Float32Array to Int16Array for Deepgram
    const float32ToInt16 = useCallback((float32Array) => {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const clamped = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
        }
        return int16Array;
    }, []);

    // Connect to Deepgram WebSocket
    const connectToDeepgram = useCallback(() => {
        if (!DEEPGRAM_API_KEY) {
            console.error("[Bot] DEEPGRAM_API_KEY is missing");
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
        console.log("[Bot] Connecting to Deepgram...");

        const socket = new WebSocket(url, ["token", DEEPGRAM_API_KEY]);

        socket.onopen = () => {
            console.log("[Bot] Deepgram connected");
            setStatus("Streaming audio to Deepgram...");
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const transcript = data?.channel?.alternatives?.[0]?.transcript || "";
                const isFinal = data?.is_final || false;

                if (transcript && isFinal) {
                    console.log(`[Bot] Transcript: ${transcript}`);
                    transcriptBuffer.addTranscript(transcript);
                    transcriptBuffer.tryCallGemini();
                }
            } catch (err) {
                console.error("[Bot] Deepgram parse error:", err);
            }
        };

        socket.onerror = (err) => {
            console.error("[Bot] Deepgram error:", err);
        };

        socket.onclose = () => {
            console.log("[Bot] Deepgram disconnected");
        };

        return socket;
    }, []);

    // Start audio capture automatically
    const startAudioCapture = useCallback(async () => {
        try {
            console.log("[Bot] Starting audio capture...");
            setStatus("Starting audio capture...");

            // Request tab audio - this requires user gesture, so we use getDisplayMedia
            // In a real bot scenario, you'd need a different approach (e.g., virtual audio device)
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    sampleRate: 48000
                }
            });

            const audioTracks = stream.getAudioTracks();
            if (audioTracks.length === 0) {
                throw new Error("No audio track - ensure 'Share tab audio' is checked");
            }

            console.log("[Bot] Audio track:", audioTracks[0].label);
            mediaStreamRef.current = stream;

            // Connect to Deepgram
            const socket = connectToDeepgram();
            if (socket) {
                deepgramSocketRef.current = socket;
            }

            // Create AudioContext
            const audioContext = new AudioContext({ sampleRate: 48000 });
            audioContextRef.current = audioContext;

            const source = audioContext.createMediaStreamSource(stream);
            const bufferSize = 4096;
            const scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);

            scriptProcessor.onaudioprocess = (event) => {
                const inputData = event.inputBuffer.getChannelData(0);

                // Send to Deepgram
                if (deepgramSocketRef.current?.readyState === WebSocket.OPEN) {
                    const int16Data = float32ToInt16(inputData);
                    deepgramSocketRef.current.send(int16Data.buffer);
                }
            };

            source.connect(scriptProcessor);
            scriptProcessor.connect(audioContext.destination);

            setIsCapturing(true);
            setStatus("Bot active - capturing audio");

            // Handle stream end
            stream.getVideoTracks()[0].onended = () => {
                console.log("[Bot] Screen sharing ended");
                cleanup();
            };

        } catch (err) {
            console.error("[Bot] Audio capture failed:", err);
            setStatus(`Audio capture failed: ${err.message}`);
        }
    }, [connectToDeepgram, float32ToInt16]);

    // Cleanup function with transcript flush
    const cleanup = useCallback(async () => {
        console.log("[Bot] Cleaning up...");
        setStatus("Shutting down...");

        // Flush any pending transcripts to Gemini before closing
        console.log("[Bot] Flushing pending transcripts...");
        try {
            await transcriptBuffer.tryCallGemini();
        } catch (err) {
            console.warn("[Bot] Failed to flush transcripts:", err);
        }

        if (deepgramSocketRef.current?.readyState === WebSocket.OPEN) {
            deepgramSocketRef.current.close();
        }
        deepgramSocketRef.current = null;

        if (audioContextRef.current) {
            audioContextRef.current.close();
        }
        audioContextRef.current = null;

        if (mediaStreamRef.current) {
            mediaStreamRef.current.getTracks().forEach(track => track.stop());
        }
        mediaStreamRef.current = null;

        transcriptBuffer.clear();
        setIsCapturing(false);
        setStatus("Bot stopped");

        // Close the window after cleanup
        console.log("[Bot] Closing window in 2 seconds...");
        setTimeout(() => {
            window.close();
        }, 2000);
    }, []);

    // Join Zoom meeting
    const joinZoomMeeting = useCallback(async (meetingDetails) => {
        try {
            const { zoomMeetingId, passcode, orgName } = meetingDetails;
            const displayName = `${orgName || "FlowSync"} Meeting Assistant`;

            console.log(`[Bot] Joining Zoom meeting ${zoomMeetingId} as "${displayName}"`);
            setStatus(`Joining meeting ${zoomMeetingId}...`);

            // Get signature from backend
            const signatureData = await authedRequest("/zoom/sdk/signature", {
                method: "POST",
                body: JSON.stringify({
                    meetingNumber: zoomMeetingId,
                    role: 0,
                }),
            });

            const signature = signatureData.signature;
            const sdkKey = import.meta.env.VITE_ZOOM_SDK_KEY;

            if (!signature) throw new Error("No signature from backend");
            if (!sdkKey) throw new Error("VITE_ZOOM_SDK_KEY missing");

            // Initialize and join
            ZoomMtg.init({
                leaveUrl: window.location.href,
                success: () => {
                    console.log("[Bot] Zoom SDK initialized");

                    ZoomMtg.join({
                        signature: signature,
                        meetingNumber: zoomMeetingId,
                        passWord: passcode || "",
                        userName: displayName,
                        success: () => {
                            console.log("[Bot] Joined Zoom meeting successfully");
                            setIsJoined(true);
                            setStatus("Joined meeting - starting audio capture...");

                            // Start audio capture after joining
                            setTimeout(() => {
                                startAudioCapture();
                            }, 3000);
                        },
                        error: (err) => {
                            console.error("[Bot] Zoom join failed:", err);
                            setStatus(`Join failed: ${err.message}`);
                        },
                    });
                },
                error: (err) => {
                    console.error("[Bot] Zoom init failed:", err);
                    setStatus(`Init failed: ${err.message}`);
                },
            });

            // Listen for meeting end via Zoom SDK
            ZoomMtg.inMeetingServiceListener("onMeetingStatus", (data) => {
                console.log("[Bot] Meeting status:", data);
                if (data.meetingStatus === 3) { // Meeting ended
                    console.log("[Bot] Meeting ended (via Zoom SDK)");
                    cleanup();
                }
            });

        } catch (err) {
            console.error("[Bot] Join error:", err);
            setStatus(`Error: ${err.message}`);
        }
    }, [startAudioCapture, cleanup]);

    // Listen for STOP_BOT WebSocket event
    useEffect(() => {
        const connectWebSocket = async () => {
            try {
                const { auth } = await import('../config/firebase');
                const user = auth.currentUser;
                if (!user) {
                    console.log("[Bot] No user for WebSocket, will rely on Zoom SDK for shutdown");
                    return;
                }

                const token = await user.getIdToken();
                const wsUrl = `${import.meta.env.VITE_WS_URL || 'ws://localhost:9000'}/ws/notifications?token=${token}`;

                console.log("[Bot] Connecting to notification WebSocket...");
                const socket = new WebSocket(wsUrl);

                socket.onopen = () => {
                    console.log("[Bot] Notification WebSocket connected");
                };

                socket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        console.log("[Bot] WebSocket event:", data.event);

                        if (data.event === 'STOP_BOT') {
                            const payload = data.payload || {};
                            // Check if this event is for our meeting
                            if (payload.meetingId === meetingId) {
                                console.log("[Bot] Received STOP_BOT event for this meeting");
                                cleanup();
                            }
                        }
                    } catch (err) {
                        console.error("[Bot] WebSocket parse error:", err);
                    }
                };

                socket.onerror = (err) => {
                    console.warn("[Bot] Notification WebSocket error:", err);
                };

                socket.onclose = () => {
                    console.log("[Bot] Notification WebSocket closed");
                };

                // Store for cleanup
                return () => {
                    if (socket.readyState === WebSocket.OPEN) {
                        socket.close();
                    }
                };
            } catch (err) {
                console.warn("[Bot] Failed to connect notification WebSocket:", err);
            }
        };

        const cleanupPromise = connectWebSocket();

        return () => {
            cleanupPromise?.then(cleanupFn => cleanupFn?.());
        };
    }, [meetingId, cleanup]);

    // Initialize bot on mount
    useEffect(() => {
        cleanupGuardRef.current = { skip: true };

        const initBot = async () => {
            if (!meetingId) {
                setStatus("Error: No meeting ID provided");
                return;
            }

            console.log(`[Bot] Initializing for meeting ${meetingId}`);
            setStatus("Waiting for authentication...");

            // Wait for Firebase auth to be ready (popup windows need time to restore auth state)
            const waitForAuth = () => new Promise((resolve) => {
                let resolved = false;

                // If already authenticated, resolve immediately
                if (auth.currentUser) {
                    console.log("[Bot] Auth already available");
                    resolve(auth.currentUser);
                    return;
                }

                // Otherwise wait for auth state change
                console.log("[Bot] Waiting for auth state...");
                const unsubscribe = auth.onAuthStateChanged((user) => {
                    if (user && !resolved) {
                        resolved = true;
                        console.log("[Bot] Auth state received");
                        unsubscribe();
                        resolve(user);
                    }
                });

                // Timeout after 10 seconds
                setTimeout(() => {
                    if (!resolved) {
                        resolved = true;
                        unsubscribe();
                        console.warn("[Bot] Auth timeout - no user after 10s");
                        resolve(null);
                    }
                }, 10000);
            });

            const user = await waitForAuth();
            if (!user) {
                setStatus("Error: Authentication timed out");
                console.error("[Bot] No authenticated user available");
                return;
            }

            setStatus("Fetching meeting details...");

            try {
                // Fetch meeting details from backend
                const meetingDetails = await authedRequest(`/meetings/${meetingId}`);
                console.log("[Bot] Meeting details received:", JSON.stringify(meetingDetails, null, 2));

                if (!meetingDetails || !meetingDetails.zoomMeetingId) {
                    // If no Zoom meeting ID, this meeting cannot be joined as a bot
                    console.warn("[Bot] Meeting has no Zoom meeting ID:", meetingDetails);
                    setStatus(`Error: No Zoom meeting ID found. Meeting status: ${meetingDetails?.status || 'unknown'}`);
                    // Extended timeout for debugging - auto-close after 30 seconds
                    setTimeout(() => {
                        console.log("[Bot] Closing window - no Zoom meeting ID");
                        window.close();
                    }, 30000);
                    return;
                }

                console.log(`[Bot] Joining Zoom meeting: ${meetingDetails.zoomMeetingId}`);
                await joinZoomMeeting(meetingDetails);

            } catch (err) {
                console.error("[Bot] Init error:", err);
                setStatus(`Error: ${err.message}`);
            }
        };

        if (!hasInitializedRef.current) {
            hasInitializedRef.current = true;
            initBot();
        }

        return () => {
            if (cleanupGuardRef.current.skip) {
                cleanupGuardRef.current.skip = false;
                return;
            }
            cleanup();
        };
    }, [meetingId, joinZoomMeeting, cleanup]);

    // Minimal UI - mostly hidden
    return (
        <div style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "#000",
            color: "#fff",
            fontFamily: "monospace",
            padding: "20px",
            fontSize: "12px",
            overflow: "hidden"
        }}>
            <style>{`
                /* Hide Zoom UI elements for bot mode */
                #zmmtg-root {
                    display: block !important;
                    position: fixed !important;
                    top: 0 !important;
                    left: 0 !important;
                    width: 100% !important;
                    height: 100% !important;
                    z-index: 1 !important;
                }
                
                /* Hide this overlay behind Zoom */
                .bot-status {
                    position: fixed;
                    bottom: 10px;
                    left: 10px;
                    background: rgba(0,0,0,0.8);
                    padding: 10px;
                    border-radius: 4px;
                    z-index: 99999;
                    pointer-events: none;
                }
            `}</style>

            <div className="bot-status">
                <div>🤖 FlowSync Meeting Bot</div>
                <div>Meeting: {meetingId}</div>
                <div>Status: {status}</div>
                <div>Joined: {isJoined ? "✓" : "..."}</div>
                <div>Capturing: {isCapturing ? "✓" : "..."}</div>
            </div>
        </div>
    );
};

export default ZoomBotClient;