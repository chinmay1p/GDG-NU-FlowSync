import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTaskDetectionEvents } from '../hooks/useNotificationSocket';
import { approveTask, rejectTask, fetchPendingApprovals, approveTasksBatch, rejectTasksBatch } from '../services/tasksApi';
import useContextStore from '../store/contextStore';

const TaskApprovalContext = createContext({});

const PENDING_REFRESH_MS = 30000;
const SNOOZE_DURATION_MS = 30000;
const sortPendingApprovals = (items) =>
    [...items].sort((a, b) => {
        const aTime = a?.createdAt ? new Date(a.createdAt).getTime() : 0;
        const bTime = b?.createdAt ? new Date(b.createdAt).getTime() : 0;
        return bTime - aTime;
    });

/**
 * Provider for managing task approval state and WebSocket events
 */
export function TaskApprovalProvider({ children }) {
    const { taskEvents, clearTaskEvent, isConnected } = useTaskDetectionEvents();
    const context = useContextStore((state) => state.context);
    const [pendingQueue, setPendingQueue] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isSyncing, setIsSyncing] = useState(false);
    const [syncError, setSyncError] = useState(null);
    const [snoozedUntil, setSnoozedUntil] = useState(null);
    const snoozeTimerRef = useRef(null);

    const canModerate = useMemo(() => {
        if (!context) return false;
        const orgRole = (context.orgRole || '').toUpperCase();
        if (orgRole === 'ORG_ADMIN') return true;
        return (context.teams || []).some((team) => (team.role || '').toUpperCase() === 'MANAGER');
    }, [context]);

    const clearSnoozeTimer = useCallback(() => {
        if (snoozeTimerRef.current) {
            clearTimeout(snoozeTimerRef.current);
            snoozeTimerRef.current = null;
        }
    }, []);

    useEffect(() => clearSnoozeTimer, [clearSnoozeTimer]);

    useEffect(() => {
        if (!snoozedUntil) {
            clearSnoozeTimer();
            return undefined;
        }
        const msRemaining = snoozedUntil - Date.now();
        if (msRemaining <= 0) {
            setSnoozedUntil(null);
            clearSnoozeTimer();
            return undefined;
        }
        snoozeTimerRef.current = setTimeout(() => {
            setSnoozedUntil(null);
            snoozeTimerRef.current = null;
        }, msRemaining);
        return clearSnoozeTimer;
    }, [snoozedUntil, clearSnoozeTimer]);

    const upsertPendingApproval = useCallback((incoming) => {
        if (!incoming?.pendingId) {
            return;
        }
        const timestampMs = incoming.timestamp ? Number(incoming.timestamp) : null;
        const createdAt =
            incoming.createdAt || (timestampMs ? new Date(timestampMs).toISOString() : new Date().toISOString());

        const normalized = {
            ...incoming,
            createdAt,
            taskCandidates: Array.isArray(incoming.taskCandidates) ? incoming.taskCandidates : [],
        };

        setPendingQueue((prev) =>
            sortPendingApprovals([normalized, ...prev.filter((item) => item.pendingId !== normalized.pendingId)])
        );
        setSnoozedUntil(null);
    }, []);

    const loadPendingApprovals = useCallback(async () => {
        if (!canModerate) {
            setPendingQueue([]);
            setSyncError(null);
            return;
        }
        setIsSyncing(true);
        setSyncError(null);
        try {
            const data = await fetchPendingApprovals();
            const normalized = Array.isArray(data) ? data : [];
            setPendingQueue(sortPendingApprovals(normalized));
            setSnoozedUntil(null);
        } catch (error) {
            setSyncError(error.message || 'Failed to load pending tasks');
        } finally {
            setIsSyncing(false);
        }
    }, [canModerate]);

    useEffect(() => {
        if (!canModerate) {
            setPendingQueue([]);
            setSnoozedUntil(null);
            return;
        }
        loadPendingApprovals();
        const interval = setInterval(loadPendingApprovals, PENDING_REFRESH_MS);
        return () => clearInterval(interval);
    }, [canModerate, loadPendingApprovals]);

    useEffect(() => {
        if (!canModerate || taskEvents.length === 0) return;
        taskEvents.forEach((event) => {
            if (!event?.payload) return;
            upsertPendingApproval(event.payload);
            clearTaskEvent(event.id);
        });
    }, [taskEvents, canModerate, upsertPendingApproval, clearTaskEvent]);

    const activePending = pendingQueue.length ? pendingQueue[0] : null;
    const isPopupHidden = Boolean(snoozedUntil && snoozedUntil > Date.now());
    const pendingApproval = canModerate && activePending && !isPopupHidden ? activePending : null;

    const handleApprove = useCallback(
        async (pendingId, taskIndex, edits, createGithubIssue) => {
            setIsLoading(true);
            try {
                const result = await approveTask(pendingId, taskIndex, edits, createGithubIssue);
                await loadPendingApprovals();
                return result;
            } catch (error) {
                console.error('[TaskApproval] Approve failed:', error);
                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [loadPendingApprovals]
    );

    const handleReject = useCallback(
        async (pendingId, taskIndex, reason = null) => {
            setIsLoading(true);
            try {
                const result = await rejectTask(pendingId, taskIndex, reason);
                await loadPendingApprovals();
                return result;
            } catch (error) {
                console.error('[TaskApproval] Reject failed:', error);
                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [loadPendingApprovals]
    );

    const handleApproveAll = useCallback(
        async (pendingId, edits = [], createGithubIssue = false) => {
            setIsLoading(true);
            try {
                const result = await approveTasksBatch(pendingId, edits, createGithubIssue);
                await loadPendingApprovals();
                return result;
            } catch (error) {
                console.error('[TaskApproval] Batch approve failed:', error);
                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [loadPendingApprovals]
    );

    const handleRejectAll = useCallback(
        async (pendingId, taskIndexes = null, reason = null) => {
            setIsLoading(true);
            try {
                const result = await rejectTasksBatch(pendingId, taskIndexes, reason);
                await loadPendingApprovals();
                return result;
            } catch (error) {
                console.error('[TaskApproval] Batch reject failed:', error);
                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [loadPendingApprovals]
    );

    const handleClose = useCallback(() => {
        setSnoozedUntil(Date.now() + SNOOZE_DURATION_MS);
    }, []);

    const value = {
        pendingApproval,
        pendingQueue,
        pendingCount: pendingQueue.length,
        canModerate,
        isConnected,
        isLoading,
        isSyncing,
        syncError,
        handleApprove,
        handleReject,
        handleApproveAll,
        handleRejectAll,
        handleClose,
        refreshPending: loadPendingApprovals,
    };

    return (
        <TaskApprovalContext.Provider value={value}>
            {children}
        </TaskApprovalContext.Provider>
    );
}

export function useTaskApproval() {
    const context = useContext(TaskApprovalContext);
    if (!context) {
        throw new Error('useTaskApproval must be used within TaskApprovalProvider');
    }
    return context;
}

export default TaskApprovalContext;