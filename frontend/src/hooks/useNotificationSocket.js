import { useState, useEffect, useCallback, useRef } from 'react';
import { auth } from '../config/firebase';

/**
 * Hook for connecting to the notification WebSocket and receiving events
 */
export function useNotificationSocket() {
    const [isConnected, setIsConnected] = useState(false);
    const [events, setEvents] = useState([]);
    const socketRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);

    const connect = useCallback(async () => {
        try {
            const user = auth.currentUser;
            if (!user) {
                console.log('[WS] No user logged in, skipping connection');
                return;
            }

            const token = await user.getIdToken();
            const wsUrl = `${import.meta.env.VITE_WS_URL || 'ws://localhost:9000'}/ws/notifications?token=${token}`;

            console.log('[WS] Connecting to notification socket...');

            const socket = new WebSocket(wsUrl);
            socketRef.current = socket;

            socket.onopen = () => {
                console.log('[WS] Notification socket connected');
                setIsConnected(true);
            };

            socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log('[WS] Received event:', data.event, data.payload);

                    setEvents(prev => [...prev, {
                        id: Date.now(),
                        event: data.event,
                        payload: data.payload,
                        receivedAt: new Date(),
                    }]);
                } catch (err) {
                    console.error('[WS] Failed to parse message:', err);
                }
            };

            socket.onerror = (error) => {
                console.error('[WS] Socket error:', error);
            };

            socket.onclose = (event) => {
                console.log('[WS] Socket closed:', event.code, event.reason);
                setIsConnected(false);
                socketRef.current = null;

                // Reconnect after 5 seconds
                reconnectTimeoutRef.current = setTimeout(() => {
                    console.log('[WS] Attempting to reconnect...');
                    connect();
                }, 5000);
            };

        } catch (error) {
            console.error('[WS] Connection error:', error);
        }
    }, []);

    const disconnect = useCallback(() => {
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }
        if (socketRef.current) {
            socketRef.current.close();
            socketRef.current = null;
        }
        setIsConnected(false);
    }, []);

    const clearEvent = useCallback((eventId) => {
        setEvents(prev => prev.filter(e => e.id !== eventId));
    }, []);

    const clearAllEvents = useCallback(() => {
        setEvents([]);
    }, []);

    // Connect when user is authenticated
    useEffect(() => {
        const unsubscribe = auth.onAuthStateChanged((user) => {
            if (user) {
                connect();
            } else {
                disconnect();
            }
        });

        return () => {
            unsubscribe();
            disconnect();
        };
    }, [connect, disconnect]);

    return {
        isConnected,
        events,
        clearEvent,
        clearAllEvents,
    };
}

/**
 * Hook specifically for task detection events
 */
export function useTaskDetectionEvents() {
    const { isConnected, events, clearEvent, clearAllEvents } = useNotificationSocket();

    const taskEvents = events.filter(e => e.event === 'TASK_DETECTED');
    const latestTaskEvent = taskEvents.length > 0 ? taskEvents[taskEvents.length - 1] : null;

    return {
        isConnected,
        taskEvents,
        latestTaskEvent,
        clearTaskEvent: clearEvent,
        clearAllTaskEvents: clearAllEvents,
    };
}

/**
 * @deprecated Bot auto-spawn has been disabled. 
 * Use universal audio capture from the Meetings page instead.
 * This hook is kept for backwards compatibility but does nothing.
 */
export function useBotSpawner() {
    // No-op - bot auto-spawn is disabled
    // Users should use the "Capture" button on the Meetings page instead
    return {
        spawnedMeetings: new Set(),
        onBotClosed: () => { },
    };
}

export default useNotificationSocket;