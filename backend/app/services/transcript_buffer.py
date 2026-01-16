import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, List

BUFFER_WINDOW_MS = 30_000


@dataclass
class TranscriptEntry:
	text: str
	timestamp: int


class TranscriptBuffer:
	__slots__ = ('entries', 'full_entries', 'lock')

	def __init__(self) -> None:
		self.entries: Deque[TranscriptEntry] = deque()
		self.full_entries: List[TranscriptEntry] = []
		self.lock = asyncio.Lock()


class TranscriptBufferService:

                                             
	def __init__(self) -> None:
		self._buffers: Dict[str, TranscriptBuffer] = {}

                                                                      
	async def init_meeting(self, meeting_id: str) -> None:
		if meeting_id in self._buffers:
			return
		self._buffers[meeting_id] = TranscriptBuffer()

                                                                    
	async def add_final_transcript(self, meeting_id: str, *, text: str, timestamp: int) -> Optional[TranscriptEntry]:
		return await self._store_transcript(meeting_id, text=text, timestamp=timestamp, allow_duplicates=False, label='FINAL')

                                                                      
	async def add_partial_transcript(self, meeting_id: str, *, text: str, timestamp: int) -> Optional[TranscriptEntry]:
		return await self._store_transcript(meeting_id, text=text, timestamp=timestamp, allow_duplicates=True, label='PARTIAL')

                                                                                
	async def _store_transcript(self, meeting_id: str, *, text: str, timestamp: int, allow_duplicates: bool, label: str) -> Optional[TranscriptEntry]:
		buffer = self._buffers.get(meeting_id)
		if not buffer:
			buffer = TranscriptBuffer()
			self._buffers[meeting_id] = buffer

		normalized = self._normalize_text(text)
		print(f'[BUFFER][{label}] raw="{text}" normalized="{normalized}" allow_duplicates={allow_duplicates}')
		if not normalized:
			print(f'[BUFFER][{label}] skipping empty normalized text')
			return None

		if not allow_duplicates and buffer.entries and buffer.entries[-1].text == normalized:
			print(f'[BUFFER][{label}] skipping duplicate entry')
			return None

		entry = TranscriptEntry(text=normalized, timestamp=int(timestamp))

		async with buffer.lock:
			self._prune(buffer, current_ts=entry.timestamp)
			buffer.entries.append(entry)
			buffer.full_entries.append(entry)
			print(f'[BUFFER][{label}] stored entry. buffer_size={len(buffer.entries)} total_history={len(buffer.full_entries)}')

		return entry

                                                          
	async def clear_meeting(self, meeting_id: str) -> None:
		buffer = self._buffers.pop(meeting_id, None)
		if buffer:
			async with buffer.lock:
				buffer.entries.clear()
				buffer.full_entries.clear()

                                                            
	async def get_recent_entries(self, meeting_id: str):
		buffer = self._buffers.get(meeting_id)
		if not buffer:
			print(f'[BUFFER] get_recent_entries: no buffer for {meeting_id}')
			return []
		async with buffer.lock:
			self._prune(buffer, current_ts=int(time.time() * 1000))
			entries = list(buffer.entries)
			print(f'[BUFFER] get_recent_entries: returning {len(entries)} entries')
			for entry in entries:
				print(f'  - {entry.text[:60]}...')
			return entries

                                                       
	async def get_full_entries(self, meeting_id: str):
		buffer = self._buffers.get(meeting_id)
		if not buffer:
			print(f'[BUFFER] get_full_entries: no buffer for {meeting_id}')
			return []
		async with buffer.lock:
			entries = list(buffer.full_entries)
			print(f'[BUFFER] get_full_entries: returning {len(entries)} entries')
			return entries

                                                              
	def _prune(self, buffer: TranscriptBuffer, *, current_ts: int) -> None:
		cutoff = current_ts - BUFFER_WINDOW_MS
		while buffer.entries and buffer.entries[0].timestamp < cutoff:
			buffer.entries.popleft()

                                                                            
	@staticmethod
	def _normalize_text(text: str) -> str:
		cleaned = ' '.join(text.strip().split())
		if not cleaned:
			return ''
		if cleaned[-1] not in '.!?':
			cleaned = f'{cleaned}.'
		return cleaned


transcript_buffer_service = TranscriptBufferService()
