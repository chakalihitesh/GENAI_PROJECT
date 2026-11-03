// ============================================================
// CodeLens AI — Night-Sky Authentication Controller
// Manages Sign In, Google Auth, Account Creation, Password Toggle,
// Forgot Password reset, and Auth Redirects.
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    // 1. Initialize Lucide Icons
    if (window.lucide) {
        window.lucide.createIcons();
    }

    // 2. Generate Ambient Star Field
    generateStarField();

    // 3. Initialize Authentication Logic
    initAuthController();
});

// ============================================================
// STAR FIELD GENERATION
// ============================================================
function generateStarField() {
    const starField = document.getElementById("starField");
    if (!starField) return;

    // Create 35 randomized twinkling stars for organic night sky
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < 35; i++) {
        const star = document.createElement("span");
        star.className = "star";
        const top = Math.random() * 95;
        const left = Math.random() * 98;
        const size = Math.random() * 2 + 1; // 1px to 3px
        const delay = Math.random() * 4;
        const duration = Math.random() * 3 + 2.5;

        star.style.top = `${top.toFixed(2)}%`;
        star.style.left = `${left.toFixed(2)}%`;
        star.style.width = `${size.toFixed(1)}px`;
        star.style.height = `${size.toFixed(1)}px`;
        star.style.animationDelay = `${delay.toFixed(2)}s`;
        star.style.animationDuration = `${duration.toFixed(2)}s`;

        fragment.appendChild(star);
    }
    starField.appendChild(fragment);
}

// ============================================================
// MAIN AUTH CONTROLLER
// ============================================================
function initAuthController() {
    // Mode & View Elements
    const authModeTabs = document.getElementById("authModeTabs");
    const tabSignIn = document.getElementById("tabSignIn");
    const tabSignUp = document.getElementById("tabSignUp");
    const mainAuthPanel = document.getElementById("mainAuthPanel");
    const forgotPanel = document.getElementById("forgotPanel");

    // Header Text
    const authTitle = document.getElementById("authTitle");
    const authSubtitle = document.getElementById("authSubtitle");

    // Buttons
    const googleBtn = document.getElementById("googleBtn");
    const googleBtnText = document.getElementById("googleBtnText");
    const submitBtn = document.getElementById("submitBtn");
    const submitBtnText = document.getElementById("submitBtnText");
    const submitIcon = document.getElementById("submitIcon");
    const forgotPasswordBtn = document.getElementById("forgotPasswordBtn");
    const backToSignInBtn = document.getElementById("backToSignInBtn");
    const footerPrompt = document.getElementById("footerPrompt");
    const footerSwitchBtn = document.getElementById("footerSwitchBtn");

    // Password Visibility Toggles
    const togglePasswordBtn = document.getElementById("togglePasswordBtn");
    const passwordInput = document.getElementById("passwordInput");
    const toggleConfirmPasswordBtn = document.getElementById("toggleConfirmPasswordBtn");
    const confirmPasswordInput = document.getElementById("confirmPasswordInput");
    const confirmPasswordGroup = document.getElementById("confirmPasswordGroup");
    const passwordHint = document.getElementById("passwordHint");

    // Forms & Inputs
    const authForm = document.getElementById("authForm");
    const emailInput = document.getElementById("emailInput");
    const forgotForm = document.getElementById("forgotForm");
    const forgotEmailInput = document.getElementById("forgotEmailInput");
    const forgotSubmitBtn = document.getElementById("forgotSubmitBtn");
    const forgotSubmitText = document.getElementById("forgotSubmitText");

    // Alert Banners
    const authErrorAlert = document.getElementById("authErrorAlert");
    const authErrorText = document.getElementById("authErrorText");
    const authSuccessAlert = document.getElementById("authSuccessAlert");
    const authSuccessText = document.getElementById("authSuccessText");

    const forgotErrorAlert = document.getElementById("forgotErrorAlert");
    const forgotErrorText = document.getElementById("forgotErrorText");
    const forgotSuccessAlert = document.getElementById("forgotSuccessAlert");
    const forgotSuccessText = document.getElementById("forgotSuccessText");

    let currentMode = "signin"; // "signin" | "signup"

    // ========================================================
    // AUTO-REDIRECT IF ALREADY AUTHENTICATED
    // ========================================================
    const checkRedirect = (user) => {
        if (user) {
            console.log("User already authenticated:", user.email);
            showAuthSuccess(`Welcome back, ${user.displayName || user.email}! Redirecting...`);
            setTimeout(() => {
                window.location.replace("index.html");
            }, 350);
        }
    };

    if (window.CodeLensAuth && typeof window.CodeLensAuth.onAuthChange === "function") {
        window.CodeLensAuth.onAuthChange(checkRedirect);
    } else {
        const interval = setInterval(() => {
            if (window.CodeLensAuth && typeof window.CodeLensAuth.onAuthChange === "function") {
                clearInterval(interval);
                window.CodeLensAuth.onAuthChange(checkRedirect);
            }
        }, 100);
        setTimeout(() => clearInterval(interval), 4000);
    }

    // ========================================================
    // MODE SWITCHING (Sign In vs Create Account)
    // ========================================================
    function setMode(mode) {
        currentMode = mode;
        clearAlerts();

        if (mode === "signin") {
            tabSignIn.classList.add("active");
            tabSignIn.setAttribute("aria-selected", "true");
            tabSignUp.classList.remove("active");
            tabSignUp.setAttribute("aria-selected", "false");

            authTitle.textContent = "Welcome to CodeLense";
            authSubtitle.textContent = "Sign in to explore, analyze, and query your code repositories.";

            googleBtnText.textContent = "Continue with Google";
            submitBtnText.textContent = "Sign In";
            if (submitIcon) {
                submitIcon.setAttribute("data-lucide", "log-in");
            }

            confirmPasswordGroup.style.display = "none";
            confirmPasswordInput.required = false;
            passwordHint.style.display = "none";

            footerPrompt.textContent = "Don't have an account?";
            footerSwitchBtn.textContent = "Sign up with Google";
        } else {
            tabSignUp.classList.add("active");
            tabSignUp.setAttribute("aria-selected", "true");
            tabSignIn.classList.remove("active");
            tabSignIn.setAttribute("aria-selected", "false");

            authTitle.textContent = "Create an Account";
            authSubtitle.textContent = "Get started with AI-driven codebase understanding and analysis.";

            googleBtnText.textContent = "Sign up with Google";
            submitBtnText.textContent = "Create Account";
            if (submitIcon) {
                submitIcon.setAttribute("data-lucide", "user-plus");
            }

            confirmPasswordGroup.style.display = "flex";
            confirmPasswordInput.required = true;
            passwordHint.style.display = "block";

            footerPrompt.textContent = "Already have an account?";
            footerSwitchBtn.textContent = "Sign in";
        }

        if (window.lucide) window.lucide.createIcons();
    }

    tabSignIn.addEventListener("click", () => setMode("signin"));
    tabSignUp.addEventListener("click", () => setMode("signup"));

    // Footer Switch Button
    footerSwitchBtn.addEventListener("click", () => {
        if (currentMode === "signin") {
            // User requested: "when 'sign up' is clicked it will go google authentication after complting it will go to web application"
            // Trigger Google sign-in directly for fast 1-click onboarding!
            handleGoogleAuth();
        } else {
            setMode("signin");
        }
    });

    // ========================================================
    // PASSWORD VISIBILITY TOGGLES
    // ========================================================
    togglePasswordBtn.addEventListener("click", () => {
        const isPassword = passwordInput.type === "password";
        passwordInput.type = isPassword ? "text" : "password";
        togglePasswordBtn.title = isPassword ? "Hide password" : "Show password";
        togglePasswordBtn.innerHTML = isPassword
            ? '<i data-lucide="eye-off" id="togglePasswordIcon"></i>'
            : '<i data-lucide="eye" id="togglePasswordIcon"></i>';
        if (window.lucide) window.lucide.createIcons();
    });

    toggleConfirmPasswordBtn.addEventListener("click", () => {
        const isPassword = confirmPasswordInput.type === "password";
        confirmPasswordInput.type = isPassword ? "text" : "password";
        toggleConfirmPasswordBtn.title = isPassword ? "Hide password" : "Show password";
        toggleConfirmPasswordBtn.innerHTML = isPassword
            ? '<i data-lucide="eye-off" id="toggleConfirmPasswordIcon"></i>'
            : '<i data-lucide="eye" id="toggleConfirmPasswordIcon"></i>';
        if (window.lucide) window.lucide.createIcons();
    });

    // ========================================================
    // ALERTS & FEEDBACK HELPERS
    // ========================================================
    function clearAlerts() {
        authErrorAlert.style.display = "none";
        authSuccessAlert.style.display = "none";
        forgotErrorAlert.style.display = "none";
        forgotSuccessAlert.style.display = "none";
    }

    function showAuthError(msg) {
        authErrorText.textContent = msg;
        authErrorAlert.style.display = "flex";
        authSuccessAlert.style.display = "none";
    }

    function showAuthSuccess(msg) {
        authSuccessText.textContent = msg;
        authSuccessAlert.style.display = "flex";
        authErrorAlert.style.display = "none";
    }

    function showForgotError(msg) {
        forgotErrorText.textContent = msg;
        forgotErrorAlert.style.display = "flex";
        forgotSuccessAlert.style.display = "none";
    }

    function showForgotSuccess(msg) {
        forgotSuccessText.textContent = msg;
        forgotSuccessAlert.style.display = "flex";
        forgotErrorAlert.style.display = "none";
    }

    // ========================================================
    // GOOGLE AUTHENTICATION
    // ========================================================
    async function handleGoogleAuth() {
        clearAlerts();
        googleBtn.disabled = true;
        const originalContent = googleBtn.innerHTML;
        googleBtn.innerHTML = '<span class="spinner"></span><span>Connecting to Google...</span>';

        try {
            if (!window.CodeLensAuth) {
                showAuthError("Authentication system is connecting. Please try again in a moment.");
                return;
            }

            const res = await window.CodeLensAuth.googleLogin();
            if (res && res.success) {
                const user = res.user;
                const name = user.displayName || user.email;
                showAuthSuccess(`Authenticated as ${name}! Opening CodeLens AI...`);
                setTimeout(() => {
                    window.location.replace("index.html");
                }, 400);
            } else {
                showAuthError(res ? res.error : "Google sign-in could not be completed.");
            }
        } catch (err) {
            showAuthError(err.message || "An unexpected error occurred during Google sign-in.");
        } finally {
            googleBtn.disabled = false;
            googleBtn.innerHTML = originalContent;
            if (window.lucide) window.lucide.createIcons();
        }
    }

    googleBtn.addEventListener("click", handleGoogleAuth);

    // ========================================================
    // EMAIL & PASSWORD AUTHENTICATION
    // ========================================================
    authForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearAlerts();

        const email = emailInput.value.trim();
        const password = passwordInput.value;
        const confirmPassword = confirmPasswordInput.value;

        // Validation
        if (!email) {
            showAuthError("Please enter your email address.");
            emailInput.focus();
            return;
        }

        const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailPattern.test(email)) {
            showAuthError("Please enter a valid email address (e.g. user@example.com).");
            emailInput.focus();
            return;
        }

        if (!password) {
            showAuthError("Please enter your password.");
            passwordInput.focus();
            return;
        }

        if (password.length < 6) {
            showAuthError("Password must be at least 6 characters in length.");
            passwordInput.focus();
            return;
        }

        if (currentMode === "signup") {
            if (password !== confirmPassword) {
                showAuthError("Passwords do not match. Please re-enter.");
                confirmPasswordInput.focus();
                return;
            }
        }

        // Set Loading State
        submitBtn.disabled = true;
        const prevText = submitBtnText.textContent;
        submitBtn.innerHTML = `<span class="spinner"></span><span>${currentMode === "signup" ? "Creating Account..." : "Signing In..."}</span>`;

        try {
            if (!window.CodeLensAuth) {
                showAuthError("Authentication service is initializing. Please wait...");
                return;
            }

            let res;
            if (currentMode === "signup") {
                res = await window.CodeLensAuth.registerUser(email, password);
            } else {
                res = await window.CodeLensAuth.loginUser(email, password);
            }

            if (res && res.success) {
                const user = res.user;
                const name = user.displayName || user.email;
                showAuthSuccess(
                    currentMode === "signup"
                        ? `Account created! Welcome, ${name}. Opening CodeLens AI...`
                        : `Welcome back, ${name}! Opening CodeLens AI...`
                );
                setTimeout(() => {
                    window.location.replace("index.html");
                }, 400);
            } else {
                showAuthError(res ? res.error : "Authentication failed. Please try again.");
            }
        } catch (err) {
            showAuthError(err.message || "An unexpected error occurred.");
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `
                <i data-lucide="${currentMode === "signup" ? "user-plus" : "log-in"}" id="submitIcon"></i>
                <span id="submitBtnText">${prevText}</span>
            `;
            if (window.lucide) window.lucide.createIcons();
        }
    });

    // ========================================================
    // FORGOT PASSWORD VIEW SWITCHING & SUBMISSION
    // ========================================================
    forgotPasswordBtn.addEventListener("click", () => {
        clearAlerts();
        mainAuthPanel.classList.add("hidden");
        forgotPanel.classList.remove("hidden");
        authModeTabs.style.display = "none";

        authTitle.textContent = "Reset Your Password";
        authSubtitle.textContent = "Enter your registered email and we'll send a password reset link to your inbox.";

        // Pre-fill email from main form if present
        if (emailInput.value.trim()) {
            forgotEmailInput.value = emailInput.value.trim();
        }
        forgotEmailInput.focus();
        if (window.lucide) window.lucide.createIcons();
    });

    backToSignInBtn.addEventListener("click", () => {
        clearAlerts();
        forgotPanel.classList.add("hidden");
        mainAuthPanel.classList.remove("hidden");
        authModeTabs.style.display = "flex";
        setMode(currentMode);
    });

    forgotForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearAlerts();

        const email = forgotEmailInput.value.trim();
        if (!email) {
            showForgotError("Please enter your registered email address.");
            forgotEmailInput.focus();
            return;
        }

        const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailPattern.test(email)) {
            showForgotError("Please enter a valid email address.");
            forgotEmailInput.focus();
            return;
        }

        forgotSubmitBtn.disabled = true;
        const originalText = forgotSubmitText.textContent;
        forgotSubmitBtn.innerHTML = '<span class="spinner"></span><span>Sending link...</span>';

        try {
            if (!window.CodeLensAuth) {
                showForgotError("Authentication service is initializing. Please try again.");
                return;
            }

            const res = await window.CodeLensAuth.resetPassword(email);
            if (res && res.success) {
                showForgotSuccess(`Password reset email sent to ${email}! Please check your inbox or spam folder.`);
                forgotForm.reset();
            } else {
                showForgotError(res ? res.error : "Failed to send password reset email.");
            }
        } catch (err) {
            showForgotError(err.message || "Failed to send reset email.");
        } finally {
            forgotSubmitBtn.disabled = false;
            forgotSubmitBtn.innerHTML = `
                <i data-lucide="send" id="forgotSubmitIcon"></i>
                <span id="forgotSubmitText">${originalText}</span>
            `;
            if (window.lucide) window.lucide.createIcons();
        }
    });
}
