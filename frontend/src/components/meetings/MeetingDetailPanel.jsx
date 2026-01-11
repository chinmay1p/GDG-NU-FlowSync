const formatDateTime = (value) => {
	if (!value) return '—'
	const date = new Date(value)
	if (Number.isNaN(date.getTime())) return value
	return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const formatTimestamp = (value) => {
	if (!value) return '—'
	const date = new Date(value)
	if (Number.isNaN(date.getTime())) return '—'
	return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

const SummaryList = ({ title, items }) => {
	if (!items || !items.length) return null
	return (
		<div>
			<p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
			<ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
				{items.map((item, idx) => (
					<li key={`${title}-${idx}`}>{item}</li>
				))}
			</ul>
		</div>
	)
}

const MeetingDetailPanel = ({ meeting, summary, transcript, isLoading, error, onClose }) => {
	if (!meeting) return null

	const segments = transcript?.segments || []
	const summaryGenerated = summary?.generated && summary?.summary

	const copyTranscript = () => {
		if (!segments.length) return
		try {
			const text = segments.map((segment) => segment.text).join(' ')
			if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
				navigator.clipboard.writeText(text)
			}
		} catch (err) {
			// best effort copy
		}
	}

	return (
		<div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-sm">
			<div className="flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
				<header className="border-b border-slate-200 px-6 py-4">
					<div className="flex items-start justify-between">
						<div>
							<p className="text-xs uppercase tracking-[0.3em] text-slate-500">Meeting History</p>
							<h2 className="text-2xl font-semibold text-slate-900">{meeting.title || meeting.topic || 'Untitled meeting'}</h2>
							<p className="text-sm text-slate-500">{formatDateTime(meeting.startedAt || meeting.startTime)} · Team {meeting.teamId || '—'}</p>
						</div>
						<button onClick={onClose} className="rounded-full p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
							<svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					</div>
				</header>

				<div className="flex-1 overflow-y-auto px-6 py-5">
					{isLoading && (
						<div className="mb-4 rounded-xl bg-indigo-50 px-4 py-3 text-sm text-indigo-700">Loading meeting data…</div>
					)}
					{error && (
						<div className="mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
					)}

					<section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-xs uppercase tracking-[0.3em] text-slate-500">AI Summary</p>
								<h3 className="text-lg font-semibold text-slate-900">Key Takeaways</h3>
							</div>
							<span
								className={`rounded-full px-3 py-1 text-xs font-semibold ${summaryGenerated ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}
							>
								{summaryGenerated ? 'Generated' : 'Pending'}
							</span>
						</div>
						{summaryGenerated ? (
							<div className="space-y-4 text-sm leading-relaxed text-slate-700">
								<p>{summary.summary}</p>
								<div className="grid gap-4 md:grid-cols-2">
									<SummaryList title="Key Decisions" items={summary.keyDecisions} />
									<SummaryList title="Action Items" items={summary.actionItems} />
									<SummaryList title="Topics" items={summary.topics} />
									<SummaryList title="Blockers" items={summary.blockers} />
								</div>
							</div>
						) : (
							<p className="text-sm text-slate-500">Summary not available yet. End the meeting to trigger Gemini summarization.</p>
						)}
					</section>

					<section className="mt-5 space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-xs uppercase tracking-[0.3em] text-slate-500">Full Transcript</p>
								<h3 className="text-lg font-semibold text-slate-900">{segments.length} segments</h3>
							</div>
							<button
								onClick={copyTranscript}
								disabled={!segments.length}
								className="rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								Copy All
							</button>
						</div>
						{segments.length === 0 ? (
							<p className="text-sm text-slate-500">Transcript has not been captured yet.</p>
						) : (
							<div className="space-y-3">
								{segments.map((segment, index) => (
									<div key={`${segment.timestamp}-${index}`} className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
										<div className="mb-1 flex items-center justify-between text-xs text-slate-500">
											<span>{segment.speaker || 'Unknown speaker'}</span>
											<span>{formatTimestamp(segment.timestamp)}</span>
										</div>
										<p className="text-sm text-slate-800">{segment.text}</p>
									</div>
								))}
							</div>
						)}
					</section>
				</div>
			</div>
		</div>
	)
}

export default MeetingDetailPanel
