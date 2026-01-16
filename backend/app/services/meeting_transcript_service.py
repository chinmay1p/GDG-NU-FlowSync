"""
Meeting Transcript Service - Handles transcript storage and summary generation.
"""
import asyncio
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import HTTPException, status
from firebase_admin import firestore
from openai import OpenAI

from app.core.security import ensure_firebase_initialized

logger = logging.getLogger(__name__)

                                         
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

groq_client: Optional[OpenAI] = None
if GROQ_API_KEY:
    groq_client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_API_BASE)


class MeetingTranscriptService:
    """Service for managing meeting transcripts and summaries."""

    MEETINGS_COLLECTION = "meetings"
    TRANSCRIPTS_COLLECTION = "meeting_transcripts"
    SUMMARIES_COLLECTION = "meeting_summaries"

                              
    STATUS_ACTIVE = "ACTIVE"
    STATUS_COMPLETED = "COMPLETED"

    def __init__(self) -> None:
        ensure_firebase_initialized()

                                                
                       
                                                

    async def start_meeting(
        self,
        *,
        org_id: str,
        team_id: Optional[str],
        created_by: str,
        title: Optional[str] = None,
        meeting_url: Optional[str] = None,
    ) -> Dict:
        """Create a new meeting record when meeting starts."""
        return await asyncio.to_thread(
            self._start_meeting_sync,
            org_id,
            team_id,
            created_by,
            title,
            meeting_url,
        )

    def _start_meeting_sync(
        self,
        org_id: str,
        team_id: Optional[str],
        created_by: str,
        title: Optional[str],
        meeting_url: Optional[str],
    ) -> Dict:
        client = self._get_client()
        meeting_ref = client.collection(self.MEETINGS_COLLECTION).document()

        payload = {
            "meetingId": meeting_ref.id,
            "orgId": org_id,
            "teamId": team_id,
            "title": title or "Untitled Meeting",
            "meetingUrl": meeting_url,
            "createdBy": created_by,
            "startedAt": firestore.SERVER_TIMESTAMP,
            "endedAt": None,
            "status": self.STATUS_ACTIVE,
            "hasSummary": False,
        }
        meeting_ref.set(payload)

                                              
        client.collection(self.TRANSCRIPTS_COLLECTION).document(meeting_ref.id).set({
            "meetingId": meeting_ref.id,
            "orgId": org_id,
            "teamId": team_id,
            "segments": [],
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

        logger.info("Meeting %s started by %s in org %s", meeting_ref.id, created_by, org_id)
        return {"meetingId": meeting_ref.id, "status": self.STATUS_ACTIVE}

    async def end_meeting(
        self,
        *,
        meeting_id: str,
        user_id: str,
        org_id: str,
        generate_summary: bool = True,
    ) -> Dict:
        """Mark meeting as completed and optionally generate summary."""
        return await asyncio.to_thread(
            self._end_meeting_sync,
            meeting_id,
            user_id,
            org_id,
            generate_summary,
        )

    def _end_meeting_sync(
        self,
        meeting_id: str,
        user_id: str,
        org_id: str,
        generate_summary: bool,
    ) -> Dict:
        client = self._get_client()
        meeting_ref = client.collection(self.MEETINGS_COLLECTION).document(meeting_id)
        meeting_doc = meeting_ref.get()

        if not meeting_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        meeting_data = meeting_doc.to_dict() or {}

                         
        if meeting_data.get("orgId") != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        if meeting_data.get("status") == self.STATUS_COMPLETED:
            return {"meetingId": meeting_id, "status": "ALREADY_COMPLETED"}

                               
        meeting_ref.update({
            "status": self.STATUS_COMPLETED,
            "endedAt": firestore.SERVER_TIMESTAMP,
        })

        logger.info("Meeting %s ended by %s", meeting_id, user_id)

                                                                 
        summary_result = None
        if generate_summary and not meeting_data.get("hasSummary"):
            summary_result = self._generate_summary_sync(meeting_id, org_id)
            if summary_result:
                meeting_ref.update({"hasSummary": True})

        return {
            "meetingId": meeting_id,
            "status": self.STATUS_COMPLETED,
            "summaryGenerated": summary_result is not None,
        }

                                                
                        
                                                

    async def append_transcript(
        self,
        *,
        meeting_id: str,
        text: str,
        timestamp: int,
        speaker: Optional[str] = None,
        org_id: str,
        team_id: Optional[str] = None,
        allow_create: bool = False,
        created_by: Optional[str] = None,
    ) -> Dict:
        """Append a final transcript segment to the meeting."""
        return await asyncio.to_thread(
            self._append_transcript_sync,
            meeting_id,
            text,
            timestamp,
            speaker,
            org_id,
            team_id,
            allow_create,
            created_by,
        )

    def _append_transcript_sync(
        self,
        meeting_id: str,
        text: str,
        timestamp: int,
        speaker: Optional[str],
        org_id: str,
        team_id: Optional[str],
        allow_create: bool,
        created_by: Optional[str],
    ) -> Dict:
        if not text or not text.strip():
            return {"success": False, "reason": "Empty text"}

        client = self._get_client()

                                                  
        meeting_doc = client.collection(self.MEETINGS_COLLECTION).document(meeting_id).get()
        if not meeting_doc.exists:
            if not allow_create:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
            meeting_payload = {
                "meetingId": meeting_id,
                "orgId": org_id,
                "teamId": team_id,
                "title": f"Meeting {meeting_id[:8]}",
                "createdBy": created_by or "system",
                "status": self.STATUS_ACTIVE,
                "startedAt": firestore.SERVER_TIMESTAMP,
                "hasSummary": False,
            }
            client.collection(self.MEETINGS_COLLECTION).document(meeting_id).set(meeting_payload)
            meeting_data = meeting_payload
        else:
            meeting_data = meeting_doc.to_dict() or {}
            if meeting_data.get("orgId") != org_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            if team_id and not meeting_data.get("teamId"):
                client.collection(self.MEETINGS_COLLECTION).document(meeting_id).update({"teamId": team_id})
                meeting_data["teamId"] = team_id

                              
        transcript_ref = client.collection(self.TRANSCRIPTS_COLLECTION).document(meeting_id)
        transcript_doc = transcript_ref.get()
        if not transcript_doc.exists:
            transcript_ref.set({
                "meetingId": meeting_id,
                "orgId": org_id,
                "teamId": meeting_data.get("teamId"),
                "segments": [],
                "createdAt": firestore.SERVER_TIMESTAMP,
            })
        segment = {
            "text": text.strip(),
            "timestamp": timestamp,
            "speaker": speaker,
        }

        transcript_ref.update({
            "segments": firestore.ArrayUnion([segment]),
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

        return {"success": True, "segmentCount": 1}

    async def get_transcript(
        self,
        *,
        meeting_id: str,
        user_id: str,
        org_id: str,
    ) -> Dict:
        """Get full transcript for a meeting."""
        return await asyncio.to_thread(
            self._get_transcript_sync,
            meeting_id,
            user_id,
            org_id,
        )

    def _get_transcript_sync(
        self,
        meeting_id: str,
        user_id: str,
        org_id: str,
    ) -> Dict:
        client = self._get_client()

                                   
        meeting_doc = client.collection(self.MEETINGS_COLLECTION).document(meeting_id).get()
        if not meeting_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        meeting_data = meeting_doc.to_dict() or {}

                             
        if meeting_data.get("orgId") != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

                                                        
        team_id = meeting_data.get("teamId")
        if team_id:
            if not self._is_team_member(client, team_id, user_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this team")

                        
        transcript_doc = client.collection(self.TRANSCRIPTS_COLLECTION).document(meeting_id).get()
        if not transcript_doc.exists:
            return {"meetingId": meeting_id, "segments": []}

        transcript_data = transcript_doc.to_dict() or {}
        return {
            "meetingId": meeting_id,
            "segments": transcript_data.get("segments", []),
        }

                                                
                        
                                                

    def _generate_summary_sync(self, meeting_id: str, org_id: str) -> Optional[Dict]:
        """Generate meeting summary using Groq (called once at meeting end)."""
        if not groq_client:
            logger.warning("GROQ_API_KEY not set, skipping summary generation")
            return None

        client = self._get_client()

                        
        transcript_doc = client.collection(self.TRANSCRIPTS_COLLECTION).document(meeting_id).get()
        if not transcript_doc.exists:
            logger.warning("No transcript found for meeting %s", meeting_id)
            return None

        transcript_data = transcript_doc.to_dict() or {}
        segments = transcript_data.get("segments", [])

        if not segments:
            logger.warning("Empty transcript for meeting %s", meeting_id)
            return None

                                                   
        full_transcript = " ".join(seg.get("text", "") for seg in segments)

        if len(full_transcript) < 50:
            logger.info("Transcript too short for summary: %d chars", len(full_transcript))
            return None

                                    
        system_prompt = "You are a meeting summarizer. Provide accurate, structured summaries with clear actionability."
        user_prompt = f"""Analyze the following meeting transcript and provide a structured summary in JSON.

TRANSCRIPT:
\"\"\"
{full_transcript}
\"\"\"

Return ONLY valid JSON in this shape:

{{
  "title": "Brief meeting title (inferred from discussion)",
  "summary": "2-3 paragraph summary of the meeting",
  "keyDecisions": ["List of key decisions made"],
  "actionItems": ["List of action items mentioned"],
  "participants": ["Names mentioned in discussion"],
  "topics": ["Main topics discussed"],
  "blockers": ["Any blockers or concerns raised"],
  "nextSteps": ["Agreed next steps"]
}}

If something is unclear, state that explicitly and do not invent facts."""

        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )

            response_text = ""
            if response.choices:
                response_text = response.choices[0].message.content or ""

                                      
            import json
            import re

                                        
            cleaned = response_text
            if "```json" in cleaned:
                cleaned = re.sub(r"```json\s*", "", cleaned)
                cleaned = re.sub(r"```\s*", "", cleaned)
            elif "```" in cleaned:
                cleaned = re.sub(r"```\s*", "", cleaned)

                          
            json_match = re.search(r"\{[\s\S]*\}", cleaned)
            if json_match:
                summary_data = json.loads(json_match.group(0))
            else:
                summary_data = {"summary": cleaned, "error": "Could not parse structured format"}

                           
            summary_doc = {
                "meetingId": meeting_id,
                "orgId": org_id,
                **summary_data,
                "generatedAt": firestore.SERVER_TIMESTAMP,
            }

            client.collection(self.SUMMARIES_COLLECTION).document(meeting_id).set(summary_doc)

            logger.info("Summary generated for meeting %s", meeting_id)
            return summary_data

        except Exception as e:
            logger.error("Failed to generate summary for meeting %s: %s", meeting_id, e)
            return None

    async def get_summary(
        self,
        *,
        meeting_id: str,
        user_id: str,
        org_id: str,
    ) -> Dict:
        """Get meeting summary."""
        return await asyncio.to_thread(
            self._get_summary_sync,
            meeting_id,
            user_id,
            org_id,
        )

    def _get_summary_sync(
        self,
        meeting_id: str,
        user_id: str,
        org_id: str,
    ) -> Dict:
        client = self._get_client()

                                   
        meeting_doc = client.collection(self.MEETINGS_COLLECTION).document(meeting_id).get()
        if not meeting_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        meeting_data = meeting_doc.to_dict() or {}

                             
        if meeting_data.get("orgId") != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

                                                        
        team_id = meeting_data.get("teamId")
        if team_id:
            if not self._is_team_member(client, team_id, user_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this team")

                     
        summary_doc = client.collection(self.SUMMARIES_COLLECTION).document(meeting_id).get()
        if not summary_doc.exists:
            return {"meetingId": meeting_id, "summary": None, "generated": False}

        summary_data = summary_doc.to_dict() or {}
        return {
            "meetingId": meeting_id,
            "generated": True,
            **summary_data,
        }

    async def delete_meeting(
        self,
        *,
        meeting_id: str,
        org_id: str,
    ) -> Dict:
        """Permanently delete a meeting and related artifacts."""
        return await asyncio.to_thread(
            self._delete_meeting_sync,
            meeting_id,
            org_id,
        )

    def _delete_meeting_sync(
        self,
        meeting_id: str,
        org_id: str,
    ) -> Dict:
        client = self._get_client()
        meeting_ref = client.collection(self.MEETINGS_COLLECTION).document(meeting_id)
        meeting_doc = meeting_ref.get()

        if not meeting_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        meeting_data = meeting_doc.to_dict() or {}
        if meeting_data.get("orgId") != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

                                       
        meeting_ref.delete()

                                                               
        client.collection(self.TRANSCRIPTS_COLLECTION).document(meeting_id).delete()
        client.collection(self.SUMMARIES_COLLECTION).document(meeting_id).delete()

        logger.info("Meeting %s permanently deleted for org %s", meeting_id, org_id)
        return {"meetingId": meeting_id, "deleted": True}

                                                
                     
                                                

    async def list_meetings(
        self,
        *,
        user_id: str,
        org_id: str,
        team_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """List meetings for user's teams."""
        return await asyncio.to_thread(
            self._list_meetings_sync,
            user_id,
            org_id,
            team_id,
            limit,
        )

    def _list_meetings_sync(
        self,
        user_id: str,
        org_id: str,
        team_id: Optional[str],
        limit: int,
    ) -> List[Dict]:
        client = self._get_client()

                                     
        user_team_ids = self._get_user_team_ids(client, user_id, org_id)

                        
        query = client.collection(self.MEETINGS_COLLECTION).where("orgId", "==", org_id)

        if team_id:
                                     
            if team_id not in user_team_ids:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this team")
            query = query.where("teamId", "==", team_id)

                                                             
                                                                                                

        meetings = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            meeting_team_id = data.get("teamId")

                                                                          
            if meeting_team_id is None or meeting_team_id in user_team_ids or data.get("createdBy") == user_id:
                started_at = data.get("startedAt")
                ended_at = data.get("endedAt")

                                                        
                topic = data.get("topic") or data.get("title") or "Untitled Meeting"
                zoom_meeting_id_raw = data.get("zoomMeetingId") or data.get("meetingId")
                zoom_meeting_id = str(zoom_meeting_id_raw) if zoom_meeting_id_raw else None
                start_iso = started_at.isoformat() if started_at else (data.get("startTime") or None)
                end_iso = ended_at.isoformat() if ended_at else (data.get("endTime") or None)

                meetings.append({
                    "meetingId": data.get("meetingId"),
                    "orgId": data.get("orgId"),
                    "teamId": meeting_team_id,
                    "title": topic,
                    "topic": topic,
                    "zoomMeetingId": zoom_meeting_id,
                    "status": data.get("status"),
                    "createdBy": data.get("createdBy"),
                    "startedAt": start_iso,
                    "startTime": start_iso,
                    "endedAt": end_iso,
                    "hasSummary": data.get("hasSummary", False),
                                                                      
                    "joinUrl": data.get("joinUrl") or data.get("meetingUrl"),
                    "startUrl": data.get("startUrl"),
                })

                                                                                 
        meetings.sort(key=lambda x: x.get('startTime') or '', reverse=True)
        return meetings[:limit]

    async def get_meeting(
        self,
        *,
        meeting_id: str,
        user_id: str,
        org_id: str,
    ) -> Dict:
        """Get meeting metadata."""
        return await asyncio.to_thread(
            self._get_meeting_sync,
            meeting_id,
            user_id,
            org_id,
        )

    def _get_meeting_sync(
        self,
        meeting_id: str,
        user_id: str,
        org_id: str,
    ) -> Dict:
        client = self._get_client()
        meeting_doc = client.collection(self.MEETINGS_COLLECTION).document(meeting_id).get()

        if not meeting_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        data = meeting_doc.to_dict() or {}

                             
        if data.get("orgId") != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

                                                        
        team_id = data.get("teamId")
        if team_id:
            if not self._is_team_member(client, team_id, user_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this team")

                                        
        def serialize_ts(val):
            if val is None:
                return None
            if hasattr(val, 'isoformat'):
                return val.isoformat()
            return str(val) if val else None

        started_at = data.get("startedAt")
        ended_at = data.get("endedAt")
        created_at = data.get("createdAt")
        start_time = data.get("startTime")

                                                          
        return {
            "meetingId": data.get("meetingId"),
            "orgId": data.get("orgId"),
            "teamId": team_id,
            "title": data.get("title"),
            "topic": data.get("topic") or data.get("title"),
            "meetingUrl": data.get("meetingUrl"),
            "status": data.get("status"),
            "createdBy": data.get("createdBy"),
            "startedAt": serialize_ts(started_at),
            "endedAt": serialize_ts(ended_at),
            "createdAt": serialize_ts(created_at),
            "startTime": serialize_ts(start_time) if start_time else serialize_ts(started_at),
            "durationMinutes": data.get("durationMinutes"),
            "hasSummary": data.get("hasSummary", False),
                                     
            "zoomMeetingId": data.get("zoomMeetingId"),
            "joinUrl": data.get("joinUrl"),
            "startUrl": data.get("startUrl"),
            "passcode": data.get("passcode"),
        }

                                                
             
                                                

    def _is_team_member(self, client, team_id: str, user_id: str) -> bool:
        """Check if user is a member of the team."""
        member_doc = client.collection("team_members").document(f"{team_id}_{user_id}").get()
        return member_doc.exists

    def _get_user_team_ids(self, client, user_id: str, org_id: str) -> set:
        """Get all team IDs the user belongs to in the org."""
        team_ids = set()
        members_query = (
            client.collection("team_members")
            .where("uid", "==", user_id)
                                                                                           
        )
        for doc in members_query.stream():
            data = doc.to_dict() or {}
                                         
            if data.get("orgId") != org_id:
                continue
            if data.get("teamId"):
                team_ids.add(data["teamId"])
        return team_ids

    @staticmethod
    def _get_client():
        ensure_firebase_initialized()
        return firestore.client()


                           
meeting_transcript_service = MeetingTranscriptService()