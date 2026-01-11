import { useState, useEffect } from 'react';

/**
 * Enhanced Task Detection Modal with editable fields and multi-task support
 * Only shown to managers when TASK_DETECTED event is received
 */
const TaskApprovalModal = ({
    pendingId,
    meetingId,
    taskCandidates = [],
    onApprove,
    onReject,
    onApproveAll,
    onRejectAll,
    onClose,
    isLoading = false,
    isSyncing = false,
    errorMessage = null,
    pendingCount = 0,
}) => {
    const [currentIndex, setCurrentIndex] = useState(0);
    const [editedTasks, setEditedTasks] = useState([]);
    const [createGithubIssue, setCreateGithubIssue] = useState(false);
    const [statusMessage, setStatusMessage] = useState(null);
    const [batchReason, setBatchReason] = useState('');

    // Initialize edited tasks from candidates
    useEffect(() => {
        setCurrentIndex(0);
        setStatusMessage(null);
        setBatchReason('');
        setEditedTasks(
            taskCandidates.map((task) => ({
                title: task.title || '',
                description: task.description || '',
                assignee: task.assignee || '',
                priority: task.priority || 'medium',
                deadline: task.deadline || '',
                confidence: task.confidence || 0,
                processed: Boolean(task.approved || task.rejected),
            }))
        );
    }, [taskCandidates, pendingId]);

    if (!taskCandidates.length || !pendingId) return null;

    const currentTask = editedTasks[currentIndex] || {};
    const remainingTasks = editedTasks.filter((t) => !t.processed).length;
    const pendingEditPayloads = () =>
        editedTasks
            .map((task, index) => {
                if (task.processed) return null;
                return {
                    taskIndex: index,
                    edits: {
                        title: task.title,
                        description: task.description,
                        assignee: task.assignee,
                        priority: (task.priority || 'medium').toLowerCase(),
                        deadline: task.deadline,
                    },
                };
            })
            .filter(Boolean);

    const handleFieldChange = (field, value) => {
        setEditedTasks(prev => {
            const updated = [...prev];
            updated[currentIndex] = { ...updated[currentIndex], [field]: value };
            return updated;
        });
    };

    const handleApprove = async () => {
        setStatusMessage({ type: 'loading', text: 'Approving task...' });

        try {
            const edits = {
                title: currentTask.title,
                description: currentTask.description,
                assignee: currentTask.assignee,
                priority: (currentTask.priority || 'medium').toLowerCase(),
                deadline: currentTask.deadline,
            };

            await onApprove(pendingId, currentIndex, edits, createGithubIssue);

            // Mark as processed
            setEditedTasks(prev => {
                const updated = [...prev];
                updated[currentIndex] = { ...updated[currentIndex], processed: true };
                return updated;
            });

            setStatusMessage({ type: 'success', text: 'Task approved successfully!' });

            // Move to next unprocessed task or close
            setTimeout(() => {
                const nextUnprocessed = editedTasks.findIndex((t, i) => i > currentIndex && !t.processed);
                if (nextUnprocessed >= 0) {
                    setCurrentIndex(nextUnprocessed);
                    setStatusMessage(null);
                } else {
                    const prevUnprocessed = editedTasks.findIndex(t => !t.processed);
                    if (prevUnprocessed >= 0) {
                        setCurrentIndex(prevUnprocessed);
                        setStatusMessage(null);
                    } else {
                        onClose();
                    }
                }
            }, 1000);

        } catch (error) {
            setStatusMessage({ type: 'error', text: error.message || 'Failed to approve task' });
        }
    };

    const handleReject = async () => {
        setStatusMessage({ type: 'loading', text: 'Rejecting task...' });

        try {
            await onReject(pendingId, currentIndex);

            // Mark as processed
            setEditedTasks(prev => {
                const updated = [...prev];
                updated[currentIndex] = { ...updated[currentIndex], processed: true };
                return updated;
            });

            setStatusMessage({ type: 'success', text: 'Task rejected' });

            // Move to next unprocessed task or close
            setTimeout(() => {
                const nextUnprocessed = editedTasks.findIndex((t, i) => i > currentIndex && !t.processed);
                if (nextUnprocessed >= 0) {
                    setCurrentIndex(nextUnprocessed);
                    setStatusMessage(null);
                } else {
                    const prevUnprocessed = editedTasks.findIndex(t => !t.processed);
                    if (prevUnprocessed >= 0) {
                        setCurrentIndex(prevUnprocessed);
                        setStatusMessage(null);
                    } else {
                        onClose();
                    }
                }
            }, 500);

        } catch (error) {
            setStatusMessage({ type: 'error', text: error.message || 'Failed to reject task' });
        }
    };

    const handleApproveAll = async () => {
        if (!onApproveAll) return;
        const editPayload = pendingEditPayloads();
        if (editPayload.length === 0) {
            setStatusMessage({ type: 'info', text: 'All tasks already processed.' });
            return;
        }
        setStatusMessage({ type: 'loading', text: 'Approving remaining tasks...' });
        try {
            await onApproveAll(pendingId, editPayload, createGithubIssue);
            setStatusMessage({ type: 'success', text: 'All pending tasks approved.' });
        } catch (error) {
            setStatusMessage({ type: 'error', text: error.message || 'Failed to approve all tasks' });
        }
    };

    const handleRejectAll = async () => {
        if (!onRejectAll) return;
        const indexes = editedTasks
            .map((task, index) => (!task.processed ? index : null))
            .filter((value) => value !== null);
        if (indexes.length === 0) {
            setStatusMessage({ type: 'info', text: 'All tasks already processed.' });
            return;
        }
        setStatusMessage({ type: 'loading', text: 'Rejecting remaining tasks...' });
        try {
            await onRejectAll(pendingId, indexes, batchReason || null);
            setStatusMessage({ type: 'success', text: 'All pending tasks rejected.' });
            setBatchReason('');
        } catch (error) {
            setStatusMessage({ type: 'error', text: error.message || 'Failed to reject all tasks' });
        }
    };

    const getPriorityColor = (priority) => {
        switch (priority?.toLowerCase()) {
            case 'high': return 'border-red-200 bg-red-50 text-red-700';
            case 'medium': return 'border-yellow-200 bg-yellow-50 text-yellow-700';
            case 'low': return 'border-green-200 bg-green-50 text-green-700';
            default: return 'border-slate-200 bg-slate-50 text-slate-700';
        }
    };

    const getConfidenceColor = (confidence) => {
        if (confidence >= 0.8) return 'text-green-600';
        if (confidence >= 0.5) return 'text-yellow-600';
        return 'text-red-600';
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4 backdrop-blur-sm">
            <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white shadow-2xl overflow-hidden">
                {/* Header */}
                <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-4">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-xs uppercase tracking-widest text-indigo-200">AI Task Detection</p>
                            <h2 className="text-lg font-semibold text-white">Review Detected Tasks</h2>
                            <p className="text-xs text-indigo-200">Meeting ID: {meetingId || 'Unknown'}</p>
                            {pendingCount > 1 && (
                                <p className="text-xs text-indigo-200">{pendingCount} pending approvals in queue</p>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="rounded-full bg-white/20 px-3 py-1 text-sm font-medium text-white">
                                {currentIndex + 1} / {taskCandidates.length}
                            </span>
                            <button
                                onClick={onClose}
                                className="rounded-lg p-1 text-white/70 hover:bg-white/10 hover:text-white"
                            >
                                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    </div>
                    {remainingTasks !== taskCandidates.length && (
                        <p className="mt-1 text-xs text-indigo-200">
                            {remainingTasks} task{remainingTasks !== 1 ? 's' : ''} remaining to review
                        </p>
                    )}
                </div>

                {/* Body */}
                <div className="p-6 max-h-[60vh] overflow-y-auto">
                    {isSyncing && (
                        <div className="mb-3 rounded-xl bg-indigo-50 px-4 py-3 text-xs font-medium text-indigo-700">
                            Syncing latest pending tasks…
                        </div>
                    )}
                    {errorMessage && (
                        <div className="mb-3 rounded-xl bg-red-50 px-4 py-3 text-xs font-medium text-red-700">
                            {errorMessage}
                        </div>
                    )}
                    {/* Confidence indicator */}
                    <div className="mb-4 flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-500">AI Confidence</span>
                        <span className={`text-sm font-semibold ${getConfidenceColor(currentTask.confidence)}`}>
                            {((currentTask.confidence || 0) * 100).toFixed(0)}%
                        </span>
                    </div>

                    {/* Editable Fields */}
                    <div className="space-y-4">
                        {/* Title */}
                        <div>
                            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">
                                Task Title
                            </label>
                            <input
                                type="text"
                                value={currentTask.title || ''}
                                onChange={(e) => handleFieldChange('title', e.target.value)}
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                placeholder="Enter task title"
                            />
                        </div>

                        {/* Description */}
                        <div>
                            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">
                                Description
                            </label>
                            <textarea
                                value={currentTask.description || ''}
                                onChange={(e) => handleFieldChange('description', e.target.value)}
                                rows={3}
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                placeholder="Enter task description"
                            />
                        </div>

                        {/* Assignee and Priority */}
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">
                                    Assignee
                                </label>
                                <input
                                    type="text"
                                    value={currentTask.assignee || ''}
                                    onChange={(e) => handleFieldChange('assignee', e.target.value)}
                                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                    placeholder="Email or name"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">
                                    Priority
                                </label>
                                <select
                                    value={currentTask.priority || 'medium'}
                                    onChange={(e) => handleFieldChange('priority', e.target.value)}
                                    className={`w-full rounded-lg border px-3 py-2 text-sm font-medium ${getPriorityColor(currentTask.priority)}`}
                                >
                                    <option value="low">Low</option>
                                    <option value="medium">Medium</option>
                                    <option value="high">High</option>
                                </select>
                            </div>
                        </div>

                        {/* Deadline */}
                        <div>
                            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">
                                Deadline
                            </label>
                            <input
                                type="text"
                                value={currentTask.deadline || ''}
                                onChange={(e) => handleFieldChange('deadline', e.target.value)}
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                placeholder="e.g., Friday, End of week"
                            />
                        </div>

                        {/* GitHub Issue toggle */}
                        <div className="flex items-center gap-3 rounded-lg bg-slate-50 p-3">
                            <input
                                type="checkbox"
                                id="createGithub"
                                checked={createGithubIssue}
                                onChange={(e) => setCreateGithubIssue(e.target.checked)}
                                className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                            />
                            <label htmlFor="createGithub" className="text-sm text-slate-700">
                                Create GitHub issue
                            </label>
                        </div>

                        {/* Batch controls */}
                        <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
                            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Batch actions</p>
                                    <p className="text-xs text-slate-500">Affects {remainingTasks} unprocessed task{remainingTasks === 1 ? '' : 's'}</p>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <button
                                        onClick={handleRejectAll}
                                        disabled={isLoading || remainingTasks === 0}
                                        className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        Reject All
                                    </button>
                                    <button
                                        onClick={handleApproveAll}
                                        disabled={isLoading || remainingTasks === 0}
                                        className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        Approve All
                                    </button>
                                </div>
                            </div>
                            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                                Rejection reason (optional)
                            </label>
                            <input
                                type="text"
                                value={batchReason}
                                onChange={(e) => setBatchReason(e.target.value)}
                                placeholder="Add context for reject-all"
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                            />
                        </div>
                    </div>

                    {/* Status Message */}
                    {statusMessage && (
                        <div className={`mt-4 rounded-lg px-4 py-3 text-sm ${statusMessage.type === 'error' ? 'bg-red-50 text-red-700' :
                                statusMessage.type === 'success' ? 'bg-green-50 text-green-700' :
                                    'bg-slate-50 text-slate-700'
                            }`}>
                            {statusMessage.text}
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="border-t border-slate-200 bg-slate-50 px-6 py-4">
                    <div className="flex items-center justify-between">
                        {/* Task navigation */}
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
                                disabled={currentIndex === 0}
                                className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                                </svg>
                            </button>
                            <button
                                onClick={() => setCurrentIndex(Math.min(taskCandidates.length - 1, currentIndex + 1))}
                                disabled={currentIndex === taskCandidates.length - 1}
                                className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                </svg>
                            </button>
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center gap-3">
                            <button
                                onClick={handleReject}
                                disabled={isLoading || currentTask.processed}
                                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                            >
                                Reject
                            </button>
                            <button
                                onClick={handleApprove}
                                disabled={isLoading || currentTask.processed || !currentTask.title}
                                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                            >
                                Approve & Create Task
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TaskApprovalModal;