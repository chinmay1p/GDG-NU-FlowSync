import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuthStore from '../store/authStore'
import useUserContext from '../hooks/useUserContext'

const heroStats = [
	{ label: 'Teams automated', value: '4,200+' },
	{ label: 'Rituals orchestrated', value: '68K' },
	{ label: 'Avg. time saved', value: '12.5 hrs/wk' },
	{ label: 'Tasks synced to GitHub', value: '1.9M' },
]

const LandingPage = () => {
	const { user, logout, loading } = useAuthStore()
	const navigate = useNavigate()
	const { loading: contextLoading } = useUserContext()

	useEffect(() => {
		if (user && !contextLoading) {
			navigate('/loading', { replace: true })
		}
	}, [user, contextLoading, navigate])

	return (
		<div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-white via-purple-50 to-white text-slate-900">
			<div className="landing-orb landing-orb--one" aria-hidden="true"></div>
			<div className="landing-orb landing-orb--two" aria-hidden="true"></div>
			<div className="landing-orb landing-orb--three" aria-hidden="true"></div>
			<div className="landing-orb landing-orb--four" aria-hidden="true"></div>
			<div className="landing-orb landing-orb--five" aria-hidden="true"></div>
			<div className="landing-blob landing-blob--one" aria-hidden="true"></div>
			<div className="landing-blob landing-blob--two" aria-hidden="true"></div>
			<div className="landing-blob landing-blob--three" aria-hidden="true"></div>
			<div className="landing-blob landing-blob--four" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--one" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--two" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--three" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--four" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--five" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--six" aria-hidden="true"></div>
			<div className="landing-spark landing-spark--seven" aria-hidden="true"></div>
			<header className="fixed inset-x-0 top-0 z-40 border-b border-white/40 bg-white/70 backdrop-blur-xl">
				<div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
					<Link to="/" className="text-2xl font-semibold text-purple-700">FlowSync</Link>
					<nav className="hidden gap-6 text-sm font-semibold text-slate-500 md:flex">
						<a href="#platform" className="hover:text-slate-900">Platform</a>
						<a href="#stats" className="hover:text-slate-900">Stats</a>
						<a href="#foundations" className="hover:text-slate-900">Workflow</a>
					</nav>
					<div className="flex items-center gap-3">
						{user ? (
							<>
								<Link to="/dashboard/overview" className="rounded-full border border-purple-200 px-4 py-2 text-sm font-semibold text-purple-700 hover:border-purple-400">Dashboard</Link>
								<button onClick={logout} disabled={loading} className="rounded-full bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-purple-600/30 transition hover:bg-purple-500 disabled:opacity-60">
									{loading ? 'Signing out…' : 'Sign out'}
								</button>
							</>
						) : (
							<>
								<Link to="/signin" className="text-sm font-semibold text-slate-600 hover:text-slate-900">Sign in</Link>
								<Link to="/signup" className="rounded-full bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-purple-600/30 transition hover:bg-purple-500">Sign up</Link>
							</>
						)}
					</div>
				</div>
			</header>
			<main className="relative z-10 pt-32 pb-20">
				<section id="platform" className="mx-auto flex max-w-6xl flex-col items-center gap-10 px-6 text-center">
					<p className="text-xs font-semibold uppercase tracking-[0.6em] text-purple-400">Adaptive meeting OS</p>
					<h1 className="text-5xl font-semibold leading-tight text-slate-900 sm:text-6xl md:text-[4.8rem] md:leading-[1.1] -rotate-1">
						FlowSync
					</h1>
					<p className="max-w-3xl text-base text-slate-600 sm:text-lg">
						Centralize every meeting, ritual, and task in one flow. FlowSync captures conversations, automates follow-ups, and syncs owners across Slack, GitHub, and your dashboards.
					</p>
					<div className="flex flex-wrap items-center justify-center gap-4">
						<Link to="/signup" className="rounded-full bg-purple-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-purple-600/40 transition hover:bg-purple-500">Get started</Link>
					</div>
					<div className="relative w-full max-w-5xl rounded-[40px] border border-white/70 bg-white/80 p-10 shadow-2xl backdrop-blur">
						<div className="grid gap-6 text-left md:grid-cols-2">
							<div className="space-y-3">
								<p className="text-xs uppercase tracking-[0.4em] text-slate-400">Ritual streams</p>
								<h3 className="text-2xl font-semibold text-slate-900">One canvas for every standup, retro, and customer call</h3>
								<p className="text-sm text-slate-600">Smart agendas pull context, FlowSync records decisions, and tasks route instantly to the right owners.</p>
							</div>
							<div className="space-y-4">
								<div className="rounded-2xl border border-purple-100 bg-purple-50/80 px-6 py-4">
									<p className="text-xs uppercase tracking-[0.4em] text-purple-400">Automation</p>
									<p className="text-sm text-purple-900">Slack /assign → FlowSync task → GitHub issue</p>
								</div>
								<div className="rounded-2xl border border-slate-200 bg-white px-6 py-4">
									<p className="text-xs uppercase tracking-[0.4em] text-slate-400">Insights</p>
									<p className="text-sm text-slate-700">Speaker-aware notes, risk alerts, and engagement heatmaps.</p>
								</div>
							</div>
						</div>
					</div>
				</section>
				<section id="stats" className="mx-auto mt-16 max-w-5xl px-6">
					<div className="rounded-[32px] border border-white/60 bg-white/80 p-8 shadow-2xl backdrop-blur">
						<div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
							{heroStats.map((stat) => (
								<div key={stat.label} className="rounded-2xl border border-purple-50 bg-gradient-to-br from-purple-50 to-white p-4 text-center shadow">
									<p className="text-3xl font-semibold text-purple-700">{stat.value}</p>
									<p className="text-xs uppercase tracking-[0.3em] text-slate-400">{stat.label}</p>
								</div>
							))}
						</div>
					</div>
				</section>
				<section id="foundations" className="mx-auto mt-20 grid max-w-6xl gap-6 px-6 md:grid-cols-3">
					<div className="rounded-3xl border border-purple-100 bg-white/80 p-6 shadow-xl backdrop-blur">
						<p className="text-xs uppercase tracking-[0.4em] text-purple-400">Capture</p>
						<h3 className="mt-3 text-xl font-semibold text-slate-900">AI notes with context</h3>
						<p className="mt-2 text-sm text-slate-600">Layer real-time transcripts with speaker attribution, decisions, and blockers.</p>
					</div>
					<div className="rounded-3xl border border-purple-100 bg-white/80 p-6 shadow-xl backdrop-blur">
						<p className="text-xs uppercase tracking-[0.4em] text-purple-400">Automate</p>
						<h3 className="mt-3 text-xl font-semibold text-slate-900">Action routing</h3>
						<p className="mt-2 text-sm text-slate-600">Slash commands, Chrome capture, and manual inputs converge into one task graph.</p>
					</div>
					<div className="rounded-3xl border border-purple-100 bg-white/80 p-6 shadow-xl backdrop-blur">
						<p className="text-xs uppercase tracking-[0.4em] text-purple-400">Sync</p>
						<h3 className="mt-3 text-xl font-semibold text-slate-900">Governance-ready dashboards</h3>
						<p className="mt-2 text-sm text-slate-600">Feed FlowSync data into GitHub, Slack, and executive scoreboards without duplication.</p>
					</div>
				</section>
			</main>
			<footer className="relative z-10 border-t border-white/60 bg-white/70 backdrop-blur px-6 py-6">
				<div className="mx-auto flex max-w-6xl flex-col gap-3 text-sm text-slate-500 md:flex-row md:items-center md:justify-between">
					<p>© {new Date().getFullYear()} FlowSync. Meetings that move.</p>
					<div className="flex gap-4">
						<Link to="/signin" className="hover:text-purple-600">Sign in</Link>
						<Link to="/signup" className="hover:text-purple-600">Create account</Link>
						<Link to="/get-started" className="hover:text-purple-600">Workspace setup</Link>
					</div>
				</div>
			</footer>
		</div>
	)
}

export default LandingPage
