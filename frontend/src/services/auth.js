import {
	createUserWithEmailAndPassword,
	getRedirectResult,
	GoogleAuthProvider,
	signInWithEmailAndPassword,
	signInWithPopup,
	signOut,
	updateProfile,
	onAuthStateChanged,
} from 'firebase/auth'
import { auth } from '../config/firebase'

const googleProvider = new GoogleAuthProvider()

export const signInWithGoogle = async () => {
	try {
		const result = await signInWithPopup(auth, googleProvider)
		const idToken = await result.user.getIdToken()
		return {
			uid: result.user.uid,
			email: result.user.email,
			name: result.user.displayName,
			picture: result.user.photoURL,
			idToken,
		}
	} catch (error) {
		throw new Error(error.message || 'Sign-in failed')
	}
}

export const signOutUser = async () => {
	try {
		await signOut(auth)
	} catch (error) {
		throw new Error(error.message || 'Sign-out failed')
	}
}

export const signUpWithEmail = async ({ name, email, password }) => {
	try {
		const result = await createUserWithEmailAndPassword(auth, email, password)
		if (name) {
			await updateProfile(result.user, { displayName: name })
		}
		const idToken = await result.user.getIdToken()
		return {
			uid: result.user.uid,
			email: result.user.email,
			name: result.user.displayName || name || result.user.email,
			picture: result.user.photoURL,
			idToken,
		}
	} catch (error) {
		throw new Error(error.message || 'Sign-up failed')
	}
}

export const signInWithEmail = async ({ email, password }) => {
	try {
		const result = await signInWithEmailAndPassword(auth, email, password)
		const idToken = await result.user.getIdToken()
		return {
			uid: result.user.uid,
			email: result.user.email,
			name: result.user.displayName || result.user.email,
			picture: result.user.photoURL,
			idToken,
		}
	} catch (error) {
		throw new Error(error.message || 'Sign-in failed')
	}
}

export const updateDisplayName = async (displayName) => {
	if (!auth.currentUser) {
		throw new Error('Not authenticated')
	}
	await updateProfile(auth.currentUser, { displayName })
	return {
		name: auth.currentUser.displayName,
		email: auth.currentUser.email,
		picture: auth.currentUser.photoURL,
		uid: auth.currentUser.uid,
	}
}

export const verifyTokenWithBackend = async (idToken) => {
	const response = await fetch('http://localhost:9000/auth/login', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify({ idToken }),
	})
	if (!response.ok) {
		throw new Error('Token verification failed')
	}
	return response.json()
}

// Check for redirect result on page load
export const checkRedirectResult = async () => {
	try {
		const result = await getRedirectResult(auth)
		if (result) {
			const idToken = await result.user.getIdToken()
			return {
				uid: result.user.uid,
				email: result.user.email,
				name: result.user.displayName,
				picture: result.user.photoURL,
				idToken,
			}
		}
		return null
	} catch (error) {
		console.error('Redirect result error:', error)
		return null
	}
}

export const subscribeToAuthChanges = (callback) => {
	return onAuthStateChanged(auth, async (user) => {
		if (user) {
			// Ensure we get a fresh token if needed, though usually forceRefresh is false
			const idToken = await user.getIdToken()
			callback({
				uid: user.uid,
				email: user.email,
				name: user.displayName || user.email,
				picture: user.photoURL,
				idToken,
			})
		} else {
			callback(null)
		}
	})
}