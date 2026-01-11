"""
Task Approval Service - Handles AI-detected task approval workflow for managers.
"""
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from fastapi import HTTPException, status
from firebase_admin import firestore

from app.core.security import ensure_firebase_initialized
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)


class TaskApprovalService:
    """Service for managing AI-detected task approvals."""

    PENDING_TASKS_COLLECTION = "pending_task_approvals"
    TASKS_COLLECTION = "tasks"
    TEAM_MEMBERS_COLLECTION = "team_members"
    ORG_MEMBERS_COLLECTION = "org_members"

    def __init__(self) -> None:
        ensure_firebase_initialized()

    def _normalize_task_candidates(self, task_candidates: List[Dict]) -> List[Dict]:
        """Ensure every candidate carries consistent metadata for storage and UI."""
        normalized: List[Dict] = []
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for candidate in task_candidates:
            title = (candidate.get("title") or "Untitled Task").strip()
            description = (candidate.get("description") or "").strip()
            priority = (candidate.get("priority") or "medium").lower()
            assignee = (candidate.get("assignee") or candidate.get("assigneeEmail") or "").strip()
            detected_at_value = candidate.get("detectedAt")
            try:
                if isinstance(detected_at_value, (int, float)):
                    detected_at = int(detected_at_value)
                elif isinstance(detected_at_value, str):
                    detected_at = int(float(detected_at_value))
                else:
                    detected_at = now_ms
            except (TypeError, ValueError):
                detected_at = now_ms
            approved_flag = bool(candidate.get("approved"))
            rejected_flag = bool(candidate.get("rejected"))
            status_value = (candidate.get("status") or "PENDING").upper()
            if approved_flag:
                status_value = "APPROVED"
            elif rejected_flag:
                status_value = "REJECTED"
            normalized.append(
                {
                    "title": title or "Untitled Task",
                    "description": description,
                    "assignee": assignee,
                    "priority": priority if priority in {"low", "medium", "high"} else "medium",
                    "deadline": candidate.get("deadline"),
                    "confidence": candidate.get("confidence"),
                    "detectedAt": detected_at,
                    "approved": approved_flag,
                    "rejected": rejected_flag,
                    "status": status_value,
                }
            )
        normalized.sort(key=lambda item: item.get("detectedAt") or now_ms)
        return normalized

    @staticmethod
    def _all_candidates_processed(task_candidates: List[Dict]) -> bool:
        return all((item.get("status") or "PENDING") in {"APPROVED", "REJECTED"} for item in task_candidates)

    @staticmethod
    def _pending_candidate_count(task_candidates: List[Dict]) -> int:
        return sum(1 for item in task_candidates if (item.get("status") or "PENDING") not in {"APPROVED", "REJECTED"})

    # ==========================================
    # EMIT TASK DETECTED EVENT
    # ==========================================

    async def emit_task_detected(
        self,
        *,
        meeting_id: str,
        team_id: Optional[str],
        org_id: str,
        task_candidates: List[Dict],
    ) -> Dict:
        """
        Emit TASK_DETECTED WebSocket event to team managers.
        Called when Gemini returns task candidates.
        """
        if not task_candidates:
            return {"sent": False, "reason": "No task candidates"}

        # Store pending approval in Firestore
        normalized_candidates = self._normalize_task_candidates(task_candidates)
        pending_id = await asyncio.to_thread(
            self._store_pending_approval_sync,
            meeting_id,
            team_id,
            org_id,
            normalized_candidates,
        )

        # Get manager UIDs for the team
        manager_uids = await asyncio.to_thread(
            self._get_team_manager_uids_sync,
            team_id,
            org_id,
        )

        if not manager_uids:
            logger.info("No managers found for team %s in org %s", team_id, org_id)
            return {"sent": False, "reason": "No managers found", "pendingId": pending_id}

        # Emit to each manager
        payload = {
            "pendingId": pending_id,
            "meetingId": meeting_id,
            "teamId": team_id,
            "orgId": org_id,
            "taskCandidates": normalized_candidates,
            "timestamp": int(datetime.now().timestamp() * 1000),
        }

        sent_count = 0
        for manager_uid in manager_uids:
            try:
                await websocket_manager.emit_to_user(
                    manager_uid,
                    "TASK_DETECTED",
                    payload,
                )
                sent_count += 1
                logger.info("Sent TASK_DETECTED to manager %s", manager_uid)
            except Exception as e:
                logger.warning("Failed to send TASK_DETECTED to manager %s: %s", manager_uid, e)

        return {
            "sent": True,
            "pendingId": pending_id,
            "managersNotified": sent_count,
            "totalManagers": len(manager_uids),
        }

    def _store_pending_approval_sync(
        self,
        meeting_id: str,
        team_id: Optional[str],
        org_id: str,
        task_candidates: List[Dict],
    ) -> str:
        """Store pending task approval in Firestore."""
        client = self._get_client()
        pending_ref = client.collection(self.PENDING_TASKS_COLLECTION).document()

        payload = {
            "pendingId": pending_ref.id,
            "meetingId": meeting_id,
            "teamId": team_id,
            "orgId": org_id,
            "taskCandidates": task_candidates,
            "status": "PENDING",
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
        pending_ref.set(payload)

        logger.info("Stored pending approval %s for meeting %s", pending_ref.id, meeting_id)
        return pending_ref.id

    def _get_team_manager_uids_sync(
        self,
        team_id: Optional[str],
        org_id: str,
    ) -> List[str]:
        """Get UIDs of all managers for a team, or org admins if no team."""
        client = self._get_client()
        manager_uids = []

        if team_id:
            # Get team managers
            team_members_query = (
                client.collection(self.TEAM_MEMBERS_COLLECTION)
                .where(filter=firestore.FieldFilter("teamId", "==", team_id))
                .where(filter=firestore.FieldFilter("role", "==", "MANAGER"))
            )
            for doc in team_members_query.stream():
                data = doc.to_dict() or {}
                if data.get("uid"):
                    manager_uids.append(data["uid"])

        # Also include org admins
        org_members_query = (
            client.collection(self.ORG_MEMBERS_COLLECTION)
            .where(filter=firestore.FieldFilter("orgId", "==", org_id))
            .where(filter=firestore.FieldFilter("role", "==", "ORG_ADMIN"))
        )
        for doc in org_members_query.stream():
            data = doc.to_dict() or {}
            uid = data.get("uid")
            if uid and uid not in manager_uids:
                manager_uids.append(uid)

        return manager_uids

    # ==========================================
    # APPROVE TASK
    # ==========================================

    async def approve_task(
        self,
        *,
        pending_id: str,
        task_index: int,
        user_id: str,
        user_email: str,
        edits: Optional[Dict] = None,
        create_github_issue: bool = False,
    ) -> Dict:
        """
        Approve a task candidate and create the actual task.
        Only managers can approve.
        """
        return await asyncio.to_thread(
            self._approve_task_sync,
            pending_id,
            task_index,
            user_id,
            user_email,
            edits,
            create_github_issue,
        )

    def _approve_task_sync(
        self,
        pending_id: str,
        task_index: int,
        user_id: str,
        user_email: str,
        edits: Optional[Dict],
        create_github_issue: bool,
    ) -> Dict:
        client = self._get_client()

        # Get pending approval
        pending_ref = client.collection(self.PENDING_TASKS_COLLECTION).document(pending_id)
        pending_doc = pending_ref.get()

        if not pending_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending approval not found")

        pending_data = pending_doc.to_dict() or {}
        org_id = pending_data.get("orgId")
        team_id = pending_data.get("teamId")
        meeting_id = pending_data.get("meetingId")
        task_candidates = pending_data.get("taskCandidates", [])

        # Validate task index
        if task_index < 0 or task_index >= len(task_candidates):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid task index")

        # Verify user is a manager
        if not self._is_manager(client, org_id, team_id, user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers can approve tasks")

        # Get the task candidate
        task_candidate = task_candidates[task_index]

        # Apply edits if provided
        if edits:
            task_candidate = {**task_candidate, **edits}

        # Create the actual task
        task_id = self._create_task_from_approval(
            client,
            org_id=org_id,
            team_id=team_id,
            meeting_id=meeting_id,
            task_data=task_candidate,
            approved_by_uid=user_id,
            approved_by_email=user_email,
            create_github_issue=create_github_issue,
        )

        # Mark this task candidate as approved
        task_candidates[task_index]["approved"] = True
        task_candidates[task_index]["status"] = "APPROVED"
        task_candidates[task_index]["approvedTaskId"] = task_id

        pending_ref.update({
            "taskCandidates": task_candidates,
            "status": "COMPLETED" if self._all_candidates_processed(task_candidates) else "PENDING",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        logger.info("Task %s approved by %s from pending %s", task_id, user_id, pending_id)

        # Broadcast task creation
        asyncio.create_task(self._broadcast_task_created(task_id, org_id, team_id))

        return {
            "taskId": task_id,
            "pendingId": pending_id,
            "approved": True,
        }

    async def approve_all_tasks(
        self,
        *,
        pending_id: str,
        user_id: str,
        user_email: str,
        edits_by_index: Optional[Dict[int, Dict]] = None,
        create_github_issue: bool = False,
    ) -> Dict:
        return await asyncio.to_thread(
            self._approve_all_tasks_sync,
            pending_id,
            user_id,
            user_email,
            edits_by_index or {},
            create_github_issue,
        )

    def _approve_all_tasks_sync(
        self,
        pending_id: str,
        user_id: str,
        user_email: str,
        edits_by_index: Dict[int, Dict],
        create_github_issue: bool,
    ) -> Dict:
        client = self._get_client()
        pending_ref = client.collection(self.PENDING_TASKS_COLLECTION).document(pending_id)
        pending_doc = pending_ref.get()
        if not pending_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending approval not found")

        pending_data = pending_doc.to_dict() or {}
        org_id = pending_data.get("orgId")
        team_id = pending_data.get("teamId")
        meeting_id = pending_data.get("meetingId")
        task_candidates = pending_data.get("taskCandidates", [])

        if not self._is_manager(client, org_id, team_id, user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers can approve tasks")

        created_task_ids: List[str] = []
        for index, candidate in enumerate(task_candidates):
            status_value = (candidate.get("status") or "PENDING").upper()
            if status_value in {"APPROVED", "REJECTED"}:
                continue

            candidate_payload = {**candidate}
            edit_values = edits_by_index.get(index) or {}
            for key, value in edit_values.items():
                if value is not None:
                    candidate_payload[key] = value

            task_id = self._create_task_from_approval(
                client,
                org_id=org_id,
                team_id=team_id,
                meeting_id=meeting_id,
                task_data=candidate_payload,
                approved_by_uid=user_id,
                approved_by_email=user_email,
                create_github_issue=create_github_issue,
            )
            created_task_ids.append(task_id)
            task_candidates[index]["approved"] = True
            task_candidates[index]["status"] = "APPROVED"
            task_candidates[index]["approvedTaskId"] = task_id

        if not created_task_ids:
            return {
                "pendingId": pending_id,
                "approvedTaskIds": [],
                "remaining": self._pending_candidate_count(task_candidates),
            }

        pending_ref.update({
            "taskCandidates": task_candidates,
            "status": "COMPLETED" if self._all_candidates_processed(task_candidates) else "PENDING",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        for task_id in created_task_ids:
            asyncio.create_task(self._broadcast_task_created(task_id, org_id, team_id))

        return {
            "pendingId": pending_id,
            "approvedTaskIds": created_task_ids,
            "remaining": self._pending_candidate_count(task_candidates),
        }

    def _create_task_from_approval(
        self,
        client,
        *,
        org_id: str,
        team_id: Optional[str],
        meeting_id: str,
        task_data: Dict,
        approved_by_uid: str,
        approved_by_email: str,
        create_github_issue: bool,
    ) -> str:
        """Create a task in Firestore from an approved task candidate."""
        task_ref = client.collection(self.TASKS_COLLECTION).document()
        detected_at_value = task_data.get("detectedAt")
        detected_at_dt = None
        if isinstance(detected_at_value, datetime):
            detected_at_dt = detected_at_value
        else:
            try:
                if isinstance(detected_at_value, (int, float)):
                    detected_at_dt = datetime.fromtimestamp(float(detected_at_value) / 1000, tz=timezone.utc)
                elif isinstance(detected_at_value, str):
                    detected_at_dt = datetime.fromtimestamp(float(detected_at_value) / 1000, tz=timezone.utc)
            except Exception:  # pragma: no cover - defensive parsing
                detected_at_dt = None

        # Find assignee if specified
        assignee_email = task_data.get("assignee", "").strip()
        assigned_uid = None

        if assignee_email and assignee_email.lower() != "unassigned":
            # Try to find the user by email
            member_doc = self._find_org_member_by_email(client, org_id, assignee_email)
            if member_doc:
                assigned_uid = member_doc.get("uid")
                assignee_email = member_doc.get("email", assignee_email)

        # Parse due date
        due_date = None
        deadline_str = task_data.get("deadline", "")
        if deadline_str and deadline_str.lower() not in ["not specified", "unspecified", ""]:
            # Try to parse deadline (simple approach)
            try:
                from dateutil import parser
                due_date = parser.parse(deadline_str, fuzzy=True)
            except Exception:
                pass

        priority = task_data.get("priority", "medium").lower()
        if priority not in ["low", "medium", "high"]:
            priority = "medium"

        payload = {
            "taskId": task_ref.id,
            "orgId": org_id,
            "teamId": team_id,
            "meetingId": meeting_id,
            "title": task_data.get("title", "Untitled Task"),
            "description": task_data.get("description", ""),
            "assignedToEmail": assignee_email if assignee_email else None,
            "assignedUid": assigned_uid,
            "priority": priority,
            "status": "PENDING",
            "source": "AI_MEETING",
            "createdByEmail": approved_by_email,
            "createdByUid": approved_by_uid,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "dueDate": due_date,
            "confidence": task_data.get("confidence", 0.0),
            "githubIssueUrl": None,
            "githubIssueNumber": None,
        }
        if detected_at_dt:
            payload["detectedAt"] = detected_at_dt

        # Create GitHub issue if requested
        if create_github_issue:
            github_result = self._maybe_create_github_issue(
                client,
                org_id,
                payload["title"],
                payload["description"],
                assignee_email,
            )
            if github_result:
                payload["githubIssueUrl"] = github_result.get("url")
                payload["githubIssueNumber"] = github_result.get("number")

        task_ref.set(payload)
        return task_ref.id

    def _maybe_create_github_issue(
        self,
        client,
        org_id: str,
        title: str,
        description: str,
        assignee_email: Optional[str],
    ) -> Optional[Dict]:
        """Create GitHub issue if integration is enabled."""
        try:
            from app.utils.github import create_issue
            import os

            repo = os.getenv("DEFAULT_GITHUB_REPO")
            if not repo:
                return None

            result = create_issue(
                repo=repo,
                title=title,
                body=description,
            )
            return result
        except Exception as e:
            logger.warning("Failed to create GitHub issue: %s", e)
            return None

    async def _broadcast_task_created(self, task_id: str, org_id: str, team_id: Optional[str]) -> None:
        """Broadcast task creation to relevant users."""
        try:
            client = self._get_client()

            # Get all team members or org members
            if team_id:
                members_query = client.collection(self.TEAM_MEMBERS_COLLECTION).where(filter=firestore.FieldFilter("teamId", "==", team_id))
            else:
                members_query = client.collection(self.ORG_MEMBERS_COLLECTION).where(filter=firestore.FieldFilter("orgId", "==", org_id))

            user_ids = []
            for doc in members_query.stream():
                data = doc.to_dict() or {}
                if data.get("uid"):
                    user_ids.append(data["uid"])

            # Get task data
            task_doc = client.collection(self.TASKS_COLLECTION).document(task_id).get()
            task_data = task_doc.to_dict() if task_doc.exists else {}

            payload = {
                "taskId": task_id,
                "title": task_data.get("title"),
                "assignedToEmail": task_data.get("assignedToEmail"),
                "priority": task_data.get("priority"),
                "source": task_data.get("source"),
            }

            for user_id in user_ids:
                await websocket_manager.emit_to_user(user_id, "TASK_CREATED", payload)

        except Exception as e:
            logger.warning("Failed to broadcast task creation: %s", e)

    # ==========================================
    # REJECT TASK
    # ==========================================

    async def reject_task(
        self,
        *,
        pending_id: str,
        task_index: int,
        user_id: str,
        reason: Optional[str] = None,
    ) -> Dict:
        """
        Reject a task candidate (no DB write, just marks as rejected).
        Only managers can reject.
        """
        return await asyncio.to_thread(
            self._reject_task_sync,
            pending_id,
            task_index,
            user_id,
            reason,
        )

    def _reject_task_sync(
        self,
        pending_id: str,
        task_index: int,
        user_id: str,
        reason: Optional[str],
    ) -> Dict:
        client = self._get_client()

        # Get pending approval
        pending_ref = client.collection(self.PENDING_TASKS_COLLECTION).document(pending_id)
        pending_doc = pending_ref.get()

        if not pending_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending approval not found")

        pending_data = pending_doc.to_dict() or {}
        org_id = pending_data.get("orgId")
        team_id = pending_data.get("teamId")
        task_candidates = pending_data.get("taskCandidates", [])

        # Validate task index
        if task_index < 0 or task_index >= len(task_candidates):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid task index")

        # Verify user is a manager
        if not self._is_manager(client, org_id, team_id, user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers can reject tasks")

        # Mark as rejected
        task_candidates[task_index]["rejected"] = True
        task_candidates[task_index]["status"] = "REJECTED"
        task_candidates[task_index]["rejectedBy"] = user_id
        task_candidates[task_index]["rejectionReason"] = reason

        pending_ref.update({
            "taskCandidates": task_candidates,
            "status": "COMPLETED" if self._all_candidates_processed(task_candidates) else "PENDING",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        logger.info("Task %d rejected by %s from pending %s", task_index, user_id, pending_id)

        return {
            "pendingId": pending_id,
            "taskIndex": task_index,
            "rejected": True,
        }

    async def reject_all_tasks(
        self,
        *,
        pending_id: str,
        user_id: str,
        reason: Optional[str] = None,
        task_indexes: Optional[List[int]] = None,
    ) -> Dict:
        return await asyncio.to_thread(
            self._reject_all_tasks_sync,
            pending_id,
            user_id,
            reason,
            task_indexes,
        )

    def _reject_all_tasks_sync(
        self,
        pending_id: str,
        user_id: str,
        reason: Optional[str],
        task_indexes: Optional[List[int]],
    ) -> Dict:
        client = self._get_client()
        pending_ref = client.collection(self.PENDING_TASKS_COLLECTION).document(pending_id)
        pending_doc = pending_ref.get()
        if not pending_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending approval not found")

        pending_data = pending_doc.to_dict() or {}
        org_id = pending_data.get("orgId")
        team_id = pending_data.get("teamId")
        task_candidates = pending_data.get("taskCandidates", [])

        if not self._is_manager(client, org_id, team_id, user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers can reject tasks")

        available_indexes = {
            idx
            for idx, candidate in enumerate(task_candidates)
            if (candidate.get("status") or "PENDING") not in {"APPROVED", "REJECTED"}
        }
        if task_indexes is not None:
            target_indexes = set(task_indexes)
            invalid = [idx for idx in target_indexes if idx not in available_indexes]
            if invalid:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid task indexes: {invalid}")
        else:
            target_indexes = available_indexes

        rejected_count = 0
        for idx in target_indexes:
            task_candidates[idx]["rejected"] = True
            task_candidates[idx]["status"] = "REJECTED"
            task_candidates[idx]["rejectedBy"] = user_id
            task_candidates[idx]["rejectionReason"] = reason
            rejected_count += 1

        if rejected_count == 0:
            return {
                "pendingId": pending_id,
                "rejectedCount": 0,
                "remaining": self._pending_candidate_count(task_candidates),
            }

        pending_ref.update({
            "taskCandidates": task_candidates,
            "status": "COMPLETED" if self._all_candidates_processed(task_candidates) else "PENDING",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        return {
            "pendingId": pending_id,
            "rejectedCount": rejected_count,
            "remaining": self._pending_candidate_count(task_candidates),
        }

    # ==========================================
    # GET PENDING APPROVALS
    # ==========================================

    async def get_pending_approvals(
        self,
        *,
        user_id: str,
        org_id: str,
    ) -> List[Dict]:
        """Get all pending approvals for a manager."""
        return await asyncio.to_thread(
            self._get_pending_approvals_sync,
            user_id,
            org_id,
        )

    def _get_pending_approvals_sync(
        self,
        user_id: str,
        org_id: str,
    ) -> List[Dict]:
        client = self._get_client()

        # Get user's teams where they are a manager
        managed_teams = self._get_user_managed_teams(client, user_id, org_id)

        # Also check if user is org admin
        is_org_admin = self._is_org_admin(client, org_id, user_id)

        # Query pending approvals
        pending_query = (
            client.collection(self.PENDING_TASKS_COLLECTION)
            .where(filter=firestore.FieldFilter("orgId", "==", org_id))
        )

        results = []
        for doc in pending_query.stream():
            data = doc.to_dict() or {}
            team_id = data.get("teamId")
            status_value = (data.get("status") or "PENDING").upper()
            if status_value not in {"PENDING", "PARTIAL"}:
                continue

            # Check if user has access
            if is_org_admin or team_id in managed_teams or team_id is None:
                # Format timestamps
                created_at = data.get("createdAt")
                results.append({
                    "pendingId": data.get("pendingId"),
                    "meetingId": data.get("meetingId"),
                    "teamId": team_id,
                    "orgId": data.get("orgId"),
                    "taskCandidates": data.get("taskCandidates", []),
                    "status": status_value,
                    "createdAt": created_at.isoformat() if created_at else None,
                })

        results.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
        return results

    # ==========================================
    # HELPERS
    # ==========================================

    def _is_manager(self, client, org_id: str, team_id: Optional[str], user_id: str) -> bool:
        """Check if user is a manager (team manager or org admin)."""
        # Check if org admin
        if self._is_org_admin(client, org_id, user_id):
            return True

        # Check if team manager
        if team_id:
            member_doc = client.collection(self.TEAM_MEMBERS_COLLECTION).document(f"{team_id}_{user_id}").get()
            if member_doc.exists:
                data = member_doc.to_dict() or {}
                if data.get("role") == "MANAGER":
                    return True

        return False

    def _is_org_admin(self, client, org_id: str, user_id: str) -> bool:
        """Check if user is an org admin."""
        member_doc = client.collection(self.ORG_MEMBERS_COLLECTION).document(f"{org_id}_{user_id}").get()
        if member_doc.exists:
            data = member_doc.to_dict() or {}
            return data.get("role") == "ORG_ADMIN"
        return False

    def _get_user_managed_teams(self, client, user_id: str, org_id: str) -> set:
        """Get team IDs where user is a manager."""
        team_ids = set()
        members_query = (
            client.collection(self.TEAM_MEMBERS_COLLECTION)
            .where(filter=firestore.FieldFilter("uid", "==", user_id))
            .where(filter=firestore.FieldFilter("orgId", "==", org_id))
            .where(filter=firestore.FieldFilter("role", "==", "MANAGER"))
        )
        for doc in members_query.stream():
            data = doc.to_dict() or {}
            if data.get("teamId"):
                team_ids.add(data["teamId"])
        return team_ids

    def _find_org_member_by_email(self, client, org_id: str, email: str) -> Optional[Dict]:
        """Find org member by email."""
        query = (
            client.collection(self.ORG_MEMBERS_COLLECTION)
            .where(filter=firestore.FieldFilter("orgId", "==", org_id))
            .where(filter=firestore.FieldFilter("email", "==", email.lower()))
            .limit(1)
        )
        docs = list(query.stream())
        if docs:
            return docs[0].to_dict()
        return None

    @staticmethod
    def _get_client():
        ensure_firebase_initialized()
        return firestore.client()


# Export singleton instance
task_approval_service = TaskApprovalService()