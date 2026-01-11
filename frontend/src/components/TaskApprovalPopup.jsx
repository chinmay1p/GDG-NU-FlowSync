import { useTaskApproval } from '../context/TaskApprovalContext';
import TaskApprovalModal from './TaskApprovalModal';

/**
 * Global task approval popup that listens for TASK_DETECTED WebSocket events
 * and shows the approval modal to managers
 */
const TaskApprovalPopup = () => {
    const {
        pendingApproval,
        isLoading,
        isSyncing,
        syncError,
        handleApprove,
        handleReject,
        handleApproveAll,
        handleRejectAll,
        handleClose,
        pendingCount,
    } = useTaskApproval();

    if (!pendingApproval) {
        return null;
    }

    return (
        <TaskApprovalModal
            pendingId={pendingApproval.pendingId}
            meetingId={pendingApproval.meetingId}
            taskCandidates={pendingApproval.taskCandidates}
            pendingCount={pendingCount}
            onApprove={handleApprove}
            onReject={handleReject}
            onApproveAll={handleApproveAll}
            onRejectAll={handleRejectAll}
            onClose={handleClose}
            isLoading={isLoading}
            isSyncing={isSyncing}
            errorMessage={syncError}
        />
    );
};

export default TaskApprovalPopup;