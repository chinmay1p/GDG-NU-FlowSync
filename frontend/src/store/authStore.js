import { create } from 'zustand'
import {
	signInWithEmail,
	signInWithGoogle,
	signOutUser,
	signUpWithEmail,
	updateDisplayName,
	subscribeToAuthChanges,
	checkRedirectResult,
} from '../services/auth'

const formatUser = (payload) => ({
	uid: payload.uid,
	name: payload.name || payload.email,
	email: payload.email,
	picture: payload.picture || '',
})

const useAuthStore = create((set, get) => ({
	user: null,
	idToken: null,
	loading: true, // IMPORTANT: wait for Firebase on app load
	error: null,

	/* -------------------------------
	   FIREBASE AUTH STATE (APP LEVEL)
	-------------------------------- */
	setFromFirebase: (payload) => {
		if (!payload) {
			set({ user: null, idToken: null, loading: false, error: null })
			return
		}
		const { uid, email, displayName, photoURL, idToken } = payload
		set({
			user: formatUser({ uid, email, name: displayName, picture: photoURL }),
			idToken,
			loading: false,
			error: null,
		})
	},

	/* -------------------------------
	   FIREBASE AUTH STATE SYNC
	-------------------------------- */
	initializeSubscription: () => {
		const unsubscribe = subscribeToAuthChanges((userData) => {
			if (userData) {
				set({
					user: formatUser(userData),
					idToken: userData.idToken,
					loading: false,
					error: null,
				})
			} else {
				set({
					user: null,
					idToken: null,
					loading: false,
					error: null,
				})
			}
		})
		return unsubscribe
	},

	/* -------------------------------
	   REDIRECT AUTH (GOOGLE)
	-------------------------------- */
	checkRedirectAuth: async () => {
		try {
			const userData = await checkRedirectResult()
			if (userData) {
				set({
					user: formatUser(userData),
					idToken: userData.idToken,
					loading: false,
					error: null,
				})
				return true
			}
			return false
		} catch (err) {
			console.error('Redirect auth check failed:', err)
			return false
		}
	},

	/* -------------------------------
	   LOGIN METHODS
	-------------------------------- */
	loginWithGoogle: async () => {
		if (get().loading) return
		set({ loading: true, error: null })

		try {
			const userData = await signInWithGoogle()

			// If popup flow succeeded immediately
			if (userData) {
				set({
					user: formatUser(userData),
					idToken: userData.idToken,
					loading: false,
					error: null,
				})
			}
			// Otherwise, redirect flow will be handled by listener / redirect check
		} catch (err) {
			if (
				err.code === 'auth/popup-closed-by-user' ||
				err.code === 'auth/popup-blocked'
			) {
				set({ loading: false })
				return
			}
			set({ error: err.message || 'Login failed', loading: false })
		}
	},

	signInWithEmail: async (email, password) => {
		if (get().loading) return
		set({ loading: true, error: null })
		try {
			const userData = await signInWithEmail({
				email: email.trim(),
				password,
			})
			set({
				user: formatUser(userData),
				idToken: userData.idToken,
				loading: false,
				error: null,
			})
		} catch (err) {
			set({ error: err.message || 'Login failed', loading: false })
		}
	},

	signUpWithEmail: async ({ name, email, password }) => {
		if (get().loading) return
		set({ loading: true, error: null })
		try {
			const userData = await signUpWithEmail({
				name: name.trim(),
				email: email.trim(),
				password,
			})
			set({
				user: formatUser(userData),
				idToken: userData.idToken,
				loading: false,
				error: null,
			})
		} catch (err) {
			set({ error: err.message || 'Sign-up failed', loading: false })
		}
	},

	/* -------------------------------
	   LOGOUT
	-------------------------------- */
	logout: async () => {
		if (get().loading) return
		set({ loading: true, error: null })
		try {
			await signOutUser()
		} finally {
			set({ user: null, idToken: null, loading: false, error: null })
		}
	},

	/* -------------------------------
	   PROFILE UPDATE
	-------------------------------- */
	updateProfileName: async (name) => {
		if (!name || !name.trim()) {
			set({ error: 'Name is required' })
			return
		}
		set({ loading: true, error: null })
		try {
			const updated = await updateDisplayName(name.trim())
			set((state) => ({
				user: state.user
					? { ...state.user, name: updated.name }
					: {
							name: updated.name,
							email: updated.email,
							picture: updated.picture,
							uid: updated.uid,
					  },
				loading: false,
			}))
		} catch (err) {
			set({ error: err.message || 'Failed to update profile', loading: false })
		}
	},
}))

export default useAuthStore