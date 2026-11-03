// ============================================================
// CodeLens AI — Firebase Authentication Client Module
// Using Firebase 10.x Modular Web SDK
// Project ID: vbus-b49d6
// ============================================================

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-app.js";
import {
    getAuth,
    createUserWithEmailAndPassword,
    signInWithEmailAndPassword,
    GoogleAuthProvider,
    signInWithPopup,
    signOut,
    onAuthStateChanged,
    sendPasswordResetEmail
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";

// Default client configuration for Firebase project: vbus-b49d6
// Note: Client API keys and App IDs are public identifiers intended for web browsers.
// Private service account credentials and keys are kept strictly on the backend.
export const defaultFirebaseConfig = {
    apiKey: "AIzaSyACqSw3mhUcnA1Ha5nJByVsBov8iaioKCI",
    authDomain: "vbus-b49d6.firebaseapp.com",
    projectId: "vbus-b49d6",
    storageBucket: "vbus-b49d6.firebasestorage.app",
    messagingSenderId: "962026177714",
    appId: "1:962026177714:web:efc080ad3cddbbc75775ab",
    measurementId: "G-F95THPTLFY"
};

let app = null;
let auth = null;
let googleProvider = null;
let currentAuthUser = null;
let currentIdToken = null;
let authReady = false;
let initPromise = null;
const authListeners = [];

// ============================================================
// INITIALIZATION
// ============================================================

export function initFirebase() {
    if (initPromise) return initPromise;

    initPromise = (async () => {
        let config = { ...defaultFirebaseConfig };

        // Try fetching environment-configured public client values from backend
        try {
            const res = await fetch("/api/auth/config");
            if (res.ok) {
                const serverConfig = await res.json();
                if (serverConfig.apiKey && serverConfig.apiKey !== "") {
                    config.apiKey = serverConfig.apiKey;
                }
                if (serverConfig.appId && serverConfig.appId !== "") {
                    config.appId = serverConfig.appId;
                }
                if (serverConfig.projectId) {
                    config.projectId = serverConfig.projectId;
                    config.authDomain = `${serverConfig.projectId}.firebaseapp.com`;
                    config.storageBucket = `${serverConfig.projectId}.firebasestorage.app`;
                }
            }
        } catch (e) {
            // Use default config if backend is unreachable
        }

        try {
            app = initializeApp(config);
            auth = getAuth(app);
            googleProvider = new GoogleAuthProvider();
            googleProvider.setCustomParameters({ prompt: "select_account" });

            // Listen for authentication state changes
            onAuthStateChanged(auth, async (user) => {
                currentAuthUser = user;
                authReady = true;
                if (user) {
                    try {
                        currentIdToken = await user.getIdToken();
                    } catch (tokErr) {
                        currentIdToken = null;
                    }
                } else {
                    currentIdToken = null;
                }

                // Notify all subscribed listeners
                authListeners.forEach((fn) => {
                    try {
                        fn(user, currentIdToken);
                    } catch (listenerErr) {
                        console.error("Auth listener error:", listenerErr);
                    }
                });
            });

            console.log("Firebase Auth initialized successfully for project:", config.projectId);
            return { app, auth };
        } catch (err) {
            console.error("Firebase initialization failed:", err);
            authReady = true;
            throw err;
        }
    })();

    return initPromise;
}

// ============================================================
// AUTHENTICATION METHODS
// ============================================================

/**
 * Register a new user with Email and Password.
 */
export async function registerUser(email, password) {
    if (!auth) await initFirebase();
    try {
        const userCredential = await createUserWithEmailAndPassword(auth, email, password);
        return { success: true, user: userCredential.user };
    } catch (error) {
        return { success: false, error: formatAuthError(error) };
    }
}

/**
 * Log in an existing user with Email and Password.
 */
export async function loginUser(email, password) {
    if (!auth) await initFirebase();
    try {
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        return { success: true, user: userCredential.user };
    } catch (error) {
        return { success: false, error: formatAuthError(error) };
    }
}

/**
 * Sign in using Google OAuth Popup.
 */
export async function googleLogin() {
    if (!auth) await initFirebase();
    try {
        const result = await signInWithPopup(auth, googleProvider);
        return { success: true, user: result.user };
    } catch (error) {
        return { success: false, error: formatAuthError(error) };
    }
}

/**
 * Send password reset email.
 */
export async function resetPassword(email) {
    if (!auth) await initFirebase();
    try {
        await sendPasswordResetEmail(auth, email);
        return { success: true };
    } catch (error) {
        return { success: false, error: formatAuthError(error) };
    }
}

/**
 * Log out the currently authenticated user.
 */
export async function logoutUser() {
    if (!auth) await initFirebase();
    try {
        await signOut(auth);
        currentAuthUser = null;
        currentIdToken = null;
        return { success: true };
    } catch (error) {
        return { success: false, error: formatAuthError(error) };
    }
}

/**
 * Returns the currently signed-in user object or null.
 */
export function getCurrentUser() {
    return currentAuthUser;
}

/**
 * Returns the current Firebase ID token (JWT) for authenticating backend requests.
 */
export async function getIdToken() {
    if (currentAuthUser) {
        try {
            currentIdToken = await currentAuthUser.getIdToken();
            return currentIdToken;
        } catch (e) {
            return currentIdToken;
        }
    }
    return null;
}

/**
 * Subscribes a callback to auth state changes (login, logout, token refresh).
 */
export function onAuthChange(callback) {
    authListeners.push(callback);
    // If auth state has already resolved, trigger immediately
    if (authReady) {
        callback(currentAuthUser, currentIdToken);
    }
}

// ============================================================
// USER-FRIENDLY ERROR FORMATTING
// ============================================================

/**
 * Maps Firebase error codes to clear, helpful user-facing messages.
 */
export function formatAuthError(error) {
    if (!error) return "An unknown error occurred.";
    const code = error.code || "";
    const msg = error.message || "";

    switch (code) {
        case "auth/invalid-email":
            return "Please enter a valid email address.";
        case "auth/user-disabled":
            return "This user account has been disabled. Please contact support.";
        case "auth/user-not-found":
            return "No account found with this email. Please register first.";
        case "auth/wrong-password":
            return "Incorrect password. Please verify and try again.";
        case "auth/invalid-credential":
            return "Invalid email or password. Please verify your credentials.";
        case "auth/email-already-in-use":
            return "An account with this email address already exists. Please log in.";
        case "auth/weak-password":
            return "Password is too weak. Please choose at least 6 characters.";
        case "auth/popup-closed-by-user":
            return "Google sign-in popup was closed before completing.";
        case "auth/popup-blocked":
            return "Sign-in popup was blocked by your browser. Please allow popups for this site.";
        case "auth/operation-not-allowed":
            return "This sign-in method is not enabled in Firebase Console. Please enable Email/Password or Google in Console.";
        case "auth/network-request-failed":
            return "Network connection error. Please check your internet connection.";
        case "auth/invalid-api-key":
        case "auth/api-key-not-valid":
            return "Invalid Firebase API Key. Please verify your API key in Firebase Console.";
        case "auth/app-not-authorized":
            return "This domain is not authorized in Firebase Console. Add your host to Authentication > Settings > Authorized domains.";
        default:
            // Strip technical prefixes if present
            return msg.replace(/^Firebase:\s*/, "") || "Authentication failed. Please try again.";
    }
}

// Initialize on load
initFirebase();

// Expose on window.CodeLensAuth for easy access by other scripts
window.CodeLensAuth = {
    get auth() { return auth; },
    get app() { return app; },
    get isReady() { return authReady; },
    initFirebase,
    registerUser,
    loginUser,
    googleLogin,
    logoutUser,
    resetPassword,
    getCurrentUser,
    getIdToken,
    onAuthChange,
    formatAuthError,
};
