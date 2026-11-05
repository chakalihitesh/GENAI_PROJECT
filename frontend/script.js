const CODELENS_API_BASE = (function() {
    const host = window.location.hostname;
    let base = "";
    // Local development:
    if (host === "localhost" || host === "127.0.0.1") {
        base = (window.location.port === "8000" || window.location.port === "") ? "" : "http://127.0.0.1:8000";
    } else {
        // Remote deployment (Vercel, custom domain, etc.): point to Render backend
        base = "https://codelense-backend.onrender.com";
    }
    return base.replace(/\/+$/, "");
})();
const CURRENT_REPOSITORY_KEY = "codelens_current_repository";
const HISTORY_KEY = "codelens_history";
let selectedRepositoryFile = null;
let currentRepository = null;
let isBusy = false;
let activeProgressPoller = null;

function stopActiveProgressPoller() {
    if (activeProgressPoller) {
        clearInterval(activeProgressPoller);
        activeProgressPoller = null;
    }
}

async function readApiResponse(response) {
    const text = await response.text();
    if (!text) return {};
    try {
        return JSON.parse(text);
    } catch (_) {
        if (text.includes("502") || text.includes("Bad Gateway") || text.includes("<html") || text.includes("<!DOCTYPE")) {
            return {
                detail: "Backend service is currently starting up (cold start) or unreachable (502 Bad Gateway). Please wait 20-30 seconds and try again."
            };
        }
        return { detail: text };
    }
}

function apiError(data, fallback) {
    if (!data) return fallback;
    if (typeof data === "string" && data.trim()) return data;
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
    if (typeof data.message === "string" && data.message.trim()) return data.message;
    return fallback;
}

function clearCurrentRepository() {
    currentRepository = null;
    try {
        localStorage.removeItem(CURRENT_REPOSITORY_KEY);
    } catch (_) {}

    setText("currentRepositoryName", "No repository loaded");
    setText("currentRepositoryFileCount", "0 files");
    setText("breadcrumbRepositoryName", "No repository");
    setText("heroRepositoryName", "CodeLens AI");
    setText("heroRepositoryFileCount", "0");
    setText("fileCount", "0");
    setText("repositoryStatusText", "No active repository");

    const badgeContainer = document.getElementById("techBadges");
    if (badgeContainer) badgeContainer.innerHTML = "";
    const techSection = document.getElementById("techStackSection");
    if (techSection) techSection.hidden = true;

    renderRepositoryFiles([]);
}

function categorizeError(error, response, data) {
    // 1. Timeout error (AbortController timeout or request timeout)
    if (error && (error.name === "AbortError" || error.name === "TimeoutError" || (error.message && error.message.toLowerCase().includes("timeout")))) {
        return {
            type: "timeout",
            message: "The request to CodeLens backend timed out. The server may still be spinning up from cold sleep or the query took too long.",
            hint: "Please wait a moment and try asking again."
        };
    }

    // 2. Network error (TypeError: Failed to fetch, offline, DNS failure)
    if (error && (error.name === "TypeError" || error.message === "Failed to fetch" || (error.message && error.message.toLowerCase().includes("networkerror")))) {
        return {
            type: "network",
            message: "Unable to connect to CodeLens backend. The server may be waking up (cold start) or unreachable. Please wait 15–20 seconds and try again.",
            hint: "Please check that the backend is running and try again."
        };
    }

    // 3. HTTP status responses
    if (response) {
        const status = response.status;
        const serverDetail = apiError(data, "");

        if (status === 404) {
            return {
                type: "404",
                message: serverDetail || "Repository not found on server. The server may have restarted or reset its temporary storage.",
                hint: "Please click '+ New repository' to re-import or upload your project."
            };
        }

        if (status === 400 || status === 422) {
            return {
                type: "client_error",
                message: serverDetail || "Invalid request. Please check your query or input.",
                hint: null
            };
        }

        if (status === 502 || status === 503) {
            return {
                type: "cold_start",
                message: "CodeLens backend is currently waking up (cold start) or temporarily unavailable.",
                hint: "Render free tier services spin down after inactivity. Please wait 15–20 seconds and try again."
            };
        }

        if (status === 504) {
            return {
                type: "timeout",
                message: "Backend request timed out (504 Gateway Timeout). The query took too long to complete.",
                hint: "Please try asking a more specific question."
            };
        }

        if (status >= 500) {
            return {
                type: "5xx",
                message: serverDetail || `CodeLens backend encountered an error (HTTP ${status}) while processing your question.`,
                hint: "Please try again in a few moments."
            };
        }

        if (serverDetail) {
            return {
                type: "generic",
                message: serverDetail,
                hint: null
            };
        }
    }

    return {
        type: "unknown",
        message: error?.message || "Unable to reach CodeLens.",
        hint: null
    };
}

function warmupBackend() {
    try {
        fetch(`${CODELENS_API_BASE}/health`, { method: "GET" }).catch(() => {});
    } catch (_) {}
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatFileSize(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";

    const units = ["B", "KB", "MB", "GB"];
    let size = bytes;
    let index = 0;

    while (size >= 1024 && index < units.length - 1) {
        size /= 1024;
        index += 1;
    }

    return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

function showToast(message, isError = false) {
    const toast = document.getElementById("toast");
    const toastMessage = document.getElementById("toastMessage");

    if (!toast || !toastMessage) return;

    toastMessage.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.add("visible");

    window.clearTimeout(showToast.timer);

    showToast.timer = window.setTimeout(() => {
        toast.classList.remove("visible");
    }, 3500);
}

function refreshIcons() {
    if (
        window.lucide &&
        typeof window.lucide.createIcons === "function"
    ) {
        window.lucide.createIcons();
    }
}

function saveCurrentRepository(repository) {
    currentRepository = repository;

    localStorage.setItem(
        CURRENT_REPOSITORY_KEY,
        JSON.stringify(repository)
    );
}

function loadCurrentRepository() {
    try {
        const value = localStorage.getItem(
            CURRENT_REPOSITORY_KEY
        );

        return value ? JSON.parse(value) : null;
    } catch (_) {
        return null;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    refreshIcons();

    initializeSidebar();
    initializeFolders();
    initializeUploadModal();
    initializeChat();
    initializeSuggestions();
    initializeTextarea();
    initializeHistory();
    initializeFirebaseAuth();

    const saved = loadCurrentRepository();

    if (saved) {
        saveCurrentRepository(saved);
        updateRepositoryUI(saved);
    }

    // Warm up backend in the background so Render cold-start finishes sooner
    warmupBackend();
});

function initializeSidebar() {
    const sidebar = document.getElementById("sidebar");
    const menuButton = document.getElementById("mobileMenuButton");
    const overlay = document.getElementById("sidebarOverlay");

    if (!sidebar || !menuButton || !overlay) return;

    const close = () => {
        sidebar.classList.remove("open");
        overlay.classList.remove("visible");

        menuButton.setAttribute(
            "aria-expanded",
            "false"
        );
    };

    menuButton.addEventListener("click", () => {
        const opening = !sidebar.classList.contains("open");

        sidebar.classList.toggle("open", opening);
        overlay.classList.toggle("visible", opening);

        menuButton.setAttribute(
            "aria-expanded",
            String(opening)
        );
    });

    overlay.addEventListener("click", close);
}

function initializeFolders() {
    document.querySelectorAll(".tree-folder").forEach(folder => {
        folder.addEventListener("click", () => {
            const folderId = folder.dataset.folder;
            const children = document.getElementById(folderId);

            if (!children) return;

            const isOpen = children.classList.toggle(
                "collapsed"
            );

            folder.classList.toggle(
                "collapsed",
                isOpen
            );
        });
    });
    }

function initializeUploadModal() {
    const modal = document.getElementById("uploadModal");
    const openButton = document.getElementById("newProjectButton");
    const closeButton = document.getElementById("closeModal");
    const analyzeButton = document.getElementById("analyzeRepository");

    // Mode tabs
    const tabBtnZip = document.getElementById("tabBtnZip");
    const tabBtnFolder = document.getElementById("tabBtnFolder");
    const tabBtnGithub = document.getElementById("tabBtnGithub");
    const tabPanelZip = document.getElementById("tabPanelZip");
    const tabPanelFolder = document.getElementById("tabPanelFolder");
    const tabPanelGithub = document.getElementById("tabPanelGithub");

    // Inputs
    const fileInput = document.getElementById("repositoryFile");
    const folderInput = document.getElementById("repositoryFolder");
    const uploadZone = document.getElementById("uploadZone");
    const uploadFolderZone = document.getElementById("uploadFolderZone");
    const githubUrlInput = document.getElementById("githubRepoUrl");
    const githubBranchInput = document.getElementById("githubRepoBranch");

    // Selection preview
    const selectedFile = document.getElementById("selectedFile");
    const selectedName = document.getElementById("selectedFileName");
    const selectedSize = document.getElementById("selectedFileSize");
    const selectedIcon = document.getElementById("selectedFileIcon");
    const removeButton = document.getElementById("removeSelectedFile");

    // Progress elements
    const progressContainer = document.getElementById("indexingProgressContainer");
    const progressFill = document.getElementById("indexingProgressFill");
    const progressMessage = document.getElementById("indexingProgressMessage");
    const progressPercent = document.getElementById("indexingProgressPercent");

    if (!modal || !analyzeButton) {
        return;
    }

    let activeMode = "zip";
    let selectedZip = null;
    let selectedFolderFiles = [];
    let selectedGithub = null;

    const openModal = () => {
        modal.classList.add("visible");
        modal.setAttribute("aria-hidden", "false");
    };

    const closeModal = () => {
        if (isBusy) return;
        stopActiveProgressPoller();
        modal.classList.remove("visible");
        modal.setAttribute("aria-hidden", "true");
    };

    const switchTab = mode => {
        if (isBusy) return;
        activeMode = mode;

        [tabBtnZip, tabBtnFolder, tabBtnGithub].forEach(b => b?.classList.remove("active"));
        [tabPanelZip, tabPanelFolder, tabPanelGithub].forEach(p => {
            if (p) p.hidden = true;
        });

        if (mode === "zip") {
            tabBtnZip?.classList.add("active");
            if (tabPanelZip) tabPanelZip.hidden = false;
        } else if (mode === "folder") {
            tabBtnFolder?.classList.add("active");
            if (tabPanelFolder) tabPanelFolder.hidden = false;
        } else if (mode === "github") {
            tabBtnGithub?.classList.add("active");
            if (tabPanelGithub) tabPanelGithub.hidden = false;
        }

        resetSelection();
        refreshIcons();
    };

    tabBtnZip?.addEventListener("click", () => switchTab("zip"));
    tabBtnFolder?.addEventListener("click", () => switchTab("folder"));
    tabBtnGithub?.addEventListener("click", () => switchTab("github"));

    const resetSelection = () => {
        selectedZip = null;
        selectedFolderFiles = [];
        selectedGithub = null;
        selectedRepositoryFile = null;

        if (fileInput) fileInput.value = "";
        if (folderInput) folderInput.value = "";
        if (githubUrlInput) githubUrlInput.value = "";
        if (githubBranchInput) githubBranchInput.value = "";

        if (selectedFile) selectedFile.hidden = true;
        if (progressContainer) progressContainer.hidden = true;

        analyzeButton.disabled = true;
        analyzeButton.innerHTML = '<i data-lucide="scan-search"></i> Analyze repository';
        refreshIcons();
    };

    const chooseZip = file => {
        if (!file) return;
        if (!file.name.toLowerCase().endsWith(".zip")) {
            resetSelection();
            showToast("Please select a ZIP archive (.zip).", true);
            return;
        }

        selectedZip = file;
        selectedRepositoryFile = file;

        if (selectedName) selectedName.textContent = file.name;
        if (selectedSize) selectedSize.textContent = formatFileSize(file.size);
        if (selectedIcon) selectedIcon.setAttribute("data-lucide", "file-archive");
        if (selectedFile) selectedFile.hidden = false;

        analyzeButton.disabled = false;
        refreshIcons();
    };

    const chooseFolder = files => {
        if (!files || !files.length) return;

        // Filter out ignored dirs for quick client check
        const validFiles = Array.from(files).filter(f => {
            const path = f.webkitRelativePath || f.name;
            return !path.includes("node_modules/") && !path.includes(".git/") && !path.includes("__pycache__/");
        });

        if (!validFiles.length) {
            showToast("No valid source files found in selected folder.", true);
            return;
        }

        selectedFolderFiles = validFiles;
        const folderName = (files[0].webkitRelativePath || "").split("/")[0] || "Project Folder";

        if (selectedName) selectedName.textContent = folderName;
        if (selectedSize) selectedSize.textContent = `${validFiles.length} files`;
        if (selectedIcon) selectedIcon.setAttribute("data-lucide", "folder-code");
        if (selectedFile) selectedFile.hidden = false;

        analyzeButton.disabled = false;
        refreshIcons();
    };

    const checkGithubInput = () => {
        let url = (githubUrlInput?.value || "").trim();
        if (url && !url.startsWith("http://") && !url.startsWith("https://") && url.includes("github.com")) {
            url = "https://" + url.replace(/^www\./, "");
        }
        if (url && url.includes("github.com")) {
            const cleanUrl = url.replace(/\.git$/, "").replace(/\/+$/, "");
            const parts = cleanUrl.split("/").filter(Boolean);
            const repoName = parts.length >= 2 ? `${parts[parts.length - 2]}/${parts[parts.length - 1]}` : url;

            selectedGithub = {
                url: url,
                branch: (githubBranchInput?.value || "").trim() || null
            };

            if (selectedName) selectedName.textContent = repoName;
            if (selectedSize) selectedSize.textContent = "GitHub Remote";
            if (selectedIcon) selectedIcon.setAttribute("data-lucide", "git-branch");
            if (selectedFile) selectedFile.hidden = false;

            analyzeButton.disabled = false;
        } else {
            selectedGithub = null;
            if (selectedFile) selectedFile.hidden = true;
            analyzeButton.disabled = true;
        }
        refreshIcons();
    };

    githubUrlInput?.addEventListener("input", checkGithubInput);
    githubBranchInput?.addEventListener("input", checkGithubInput);

    if (openButton) openButton.addEventListener("click", openModal);
    if (closeButton) closeButton.addEventListener("click", closeModal);
    if (removeButton) removeButton.addEventListener("click", resetSelection);

    // ZIP Click / Drop
    if (uploadZone) {
        uploadZone.addEventListener("click", () => fileInput?.click());
        uploadZone.addEventListener("dragover", e => {
            e.preventDefault();
            uploadZone.classList.add("dragging");
        });
        uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragging"));
        uploadZone.addEventListener("drop", e => {
            e.preventDefault();
            uploadZone.classList.remove("dragging");
            chooseZip(e.dataTransfer.files?.[0]);
        });
    }

    fileInput?.addEventListener("change", e => chooseZip(e.target.files?.[0]));

    // Folder Click / Drop
    if (uploadFolderZone) {
        uploadFolderZone.addEventListener("click", () => folderInput?.click());
        uploadFolderZone.addEventListener("dragover", e => {
            e.preventDefault();
            uploadFolderZone.classList.add("dragging");
        });
        uploadFolderZone.addEventListener("dragleave", () => uploadFolderZone.classList.remove("dragging"));
        uploadFolderZone.addEventListener("drop", e => {
            e.preventDefault();
            uploadFolderZone.classList.remove("dragging");
            if (e.dataTransfer.files?.length) {
                chooseFolder(e.dataTransfer.files);
            }
        });
    }

    folderInput?.addEventListener("change", e => chooseFolder(e.target.files));

    analyzeButton.addEventListener("click", async () => {
        if (isBusy) return;

        await handleRepositoryProcess({
            mode: activeMode,
            zipFile: selectedZip,
            folderFiles: selectedFolderFiles,
            githubData: selectedGithub,
            button: analyzeButton,
            closeModal: closeModal,
            progressContainer,
            progressFill,
            progressMessage,
            progressPercent
        });
    });

    modal.addEventListener("click", event => {
        if (event.target === modal) closeModal();
    });
}

function updateStagePills(stage) {
    const s1 = document.getElementById("stageScanning");
    const s2 = document.getElementById("stageChunking");
    const s3 = document.getElementById("stageEmbedding");
    const s4 = document.getElementById("stageIndexing");

    const clear = () => {
        [s1, s2, s3, s4].forEach(p => {
            if (p) {
                p.classList.remove("active", "done");
            }
        });
    };

    clear();

    if (stage === "scanning") {
        s1?.classList.add("active");
    } else if (stage === "chunking") {
        s1?.classList.add("done");
        s2?.classList.add("active");
    } else if (stage === "embedding") {
        s1?.classList.add("done");
        s2?.classList.add("done");
        s3?.classList.add("active");
    } else if (stage === "indexing") {
        s1?.classList.add("done");
        s2?.classList.add("done");
        s3?.classList.add("done");
        s4?.classList.add("active");
    } else if (stage === "completed") {
        [s1, s2, s3, s4].forEach(p => p?.classList.add("done"));
    }
}

async function handleRepositoryProcess(params) {
    const {
        mode,
        zipFile,
        folderFiles,
        githubData,
        button,
        closeModal,
        progressContainer,
        progressFill,
        progressMessage,
        progressPercent
    } = params;

    isBusy = true;
    button.disabled = true;

    if (progressContainer) {
        progressContainer.hidden = false;
        if (progressFill) progressFill.style.width = "5%";
        if (progressPercent) progressPercent.textContent = "5%";
        if (progressMessage) progressMessage.textContent = "Uploading repository content...";
    }

    button.innerHTML = '<i data-lucide="loader-circle" class="codelens-spinner"></i> Uploading...';
    refreshIcons();

    let uploadData = null;
    let repoName = "Repository";

    try {
        if (mode === "zip") {
            if (!zipFile) throw new Error("No ZIP file selected.");
            repoName = zipFile.name.replace(/\.zip$/i, "");
            const formData = new FormData();
            formData.append("file", zipFile);

            const res = await fetch(`${CODELENS_API_BASE}/api/repositories/upload`, {
                method: "POST",
                body: formData
            });
            uploadData = await readApiResponse(res);
            if (!res.ok) throw new Error(apiError(uploadData, "Repository upload failed."));
        } else if (mode === "folder") {
            if (!folderFiles || !folderFiles.length) throw new Error("No folder files selected.");
            repoName = (folderFiles[0].webkitRelativePath || "").split("/")[0] || "Project Folder";

            const formData = new FormData();
            for (const f of folderFiles) {
                formData.append("files", f);
                formData.append("paths", f.webkitRelativePath || f.name);
            }

            const res = await fetch(`${CODELENS_API_BASE}/api/repositories/upload-folder`, {
                method: "POST",
                body: formData
            });
            uploadData = await readApiResponse(res);
            if (!res.ok) throw new Error(apiError(uploadData, "Folder upload failed."));
        } else if (mode === "github") {
            if (!githubData || !githubData.url) throw new Error("Please enter a valid GitHub URL.");
            const cleanUrl = githubData.url.replace(/\.git$/, "").replace(/\/+$/, "");
            const parts = cleanUrl.split("/").filter(Boolean);
            repoName = parts.length >= 2 ? parts[parts.length - 1] : "GitHub Repo";

            button.innerHTML = '<i data-lucide="loader-circle" class="codelens-spinner"></i> Cloning from GitHub...';
            refreshIcons();
            if (progressMessage) progressMessage.textContent = "Cloning repository from GitHub...";

            const res = await fetch(`${CODELENS_API_BASE}/api/repositories/github`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(githubData)
            });
            uploadData = await readApiResponse(res);
            if (!res.ok) throw new Error(apiError(uploadData, "GitHub repository import failed."));
        }

        const repository = uploadData.repository || {};
        const repositoryId = uploadData.repository_id || repository.repository_id;

        if (!repositoryId) {
            throw new Error("Backend did not return a valid repository ID.");
        }

        const state = {
            repository_id: repositoryId,
            name: repoName,
            file_count: repository.file_count || 0,
            files: repository.files || [],
            file_types: repository.file_types || {},
            updated_at: Date.now()
        };

        // Real-time UI preliminary update
        updateRepositoryUI(state);

        // Start live indexing progress polling with graceful completion & error handling
        let isDone = false;
        let consecutiveErrors = 0;

        const stopPolling = () => {
            isDone = true;
            stopActiveProgressPoller();
        };

        const startPolling = () => {
            stopPolling();
            isDone = false;
            consecutiveErrors = 0;

            activeProgressPoller = setInterval(async () => {
                if (isDone) {
                    stopPolling();
                    return;
                }
                try {
                    const pRes = await fetch(`${CODELENS_API_BASE}/api/repositories/${encodeURIComponent(repositoryId)}/progress`);
                    
                    if (pRes.status === 404) {
                        // Repository not found on server — STOP POLLING IMMEDIATELY
                        stopPolling();
                        const errData = await readApiResponse(pRes);
                        const errMsg = apiError(errData, "Repository not found on server.");
                        console.warn("Repository progress 404:", errMsg);
                        if (progressMessage) progressMessage.textContent = errMsg;
                        return;
                    }

                    if (!pRes.ok) {
                        consecutiveErrors++;
                        if (consecutiveErrors >= 5) {
                            console.warn("Too many consecutive progress polling errors. Stopping poller.");
                            stopPolling();
                        }
                        return;
                    }

                    consecutiveErrors = 0;
                    const pData = await pRes.json();
                    const pct = Math.max(10, Math.min(100, pData.progress || 0));
                    const msg = pData.message || "Indexing...";
                    const stage = pData.stage || "indexing";

                    if (progressFill) progressFill.style.width = `${pct}%`;
                    if (progressPercent) progressPercent.textContent = `${pct}%`;
                    if (progressMessage) progressMessage.textContent = msg;

                    button.innerHTML = `<i data-lucide="loader-circle" class="codelens-spinner"></i> ${escapeHtml(msg)} (${pct}%)`;
                    refreshIcons();
                    updateStagePills(stage);

                    // Stop polling if completed or failed
                    if (pData.status === "completed" || stage === "completed" || pct >= 100) {
                        stopPolling();
                    } else if (pData.status === "failed" || stage === "failed") {
                        stopPolling();
                        if (progressMessage) progressMessage.textContent = pData.message || "Indexing failed.";
                    }
                } catch (e) {
                    consecutiveErrors++;
                    if (consecutiveErrors >= 5) {
                        stopPolling();
                    }
                }
            }, 1000);
        };

        startPolling();

        // Perform Indexing
        button.innerHTML = '<i data-lucide="loader-circle" class="codelens-spinner"></i> Indexing repository...';
        refreshIcons();

        const indexResponse = await fetch(
            `${CODELENS_API_BASE}/api/repositories/${encodeURIComponent(repositoryId)}/index`,
            { method: "POST" }
        );

        stopPolling();

        const indexData = await readApiResponse(indexResponse);
        if (!indexResponse.ok) {
            throw new Error(apiError(indexData, "Repository indexing failed."));
        }

        // Finalize Progress Bar
        updateStagePills("completed");
        if (progressFill) progressFill.style.width = "100%";
        if (progressPercent) progressPercent.textContent = "100%";
        if (progressMessage) progressMessage.textContent = "Repository indexed successfully!";

        button.innerHTML = '<i data-lucide="check"></i> Repository ready';
        refreshIcons();

        saveCurrentRepository(state);
        addRepositoryToHistory(state);
        updateRepositoryUI(state);

        // Real-time project detection (tech-stack and overview)
        fetchAndRenderRepositoryDetails(repositoryId);

        showToast(`${state.name} is ready to explore.`);

        setTimeout(() => {
            closeModal();
            if (progressContainer) progressContainer.hidden = true;
        }, 900);

    } catch (error) {
        stopActiveProgressPoller();
        console.error("Repository processing error:", error);
        button.disabled = false;
        button.innerHTML = '<i data-lucide="scan-search"></i> Analyze repository';
        refreshIcons();
        if (progressContainer) progressContainer.hidden = true;
        showToast(error.message || "Failed to process repository.", true);
    } finally {
        stopActiveProgressPoller();
        isBusy = false;
    }
}

async function fetchAndRenderRepositoryDetails(repositoryId) {
    try {
        const [techRes, overviewRes, summaryRes] = await Promise.allSettled([
            fetch(`${CODELENS_API_BASE}/api/repositories/${encodeURIComponent(repositoryId)}/technology-stack`),
            fetch(`${CODELENS_API_BASE}/api/repositories/${encodeURIComponent(repositoryId)}/overview`),
            fetch(`${CODELENS_API_BASE}/api/repositories/${encodeURIComponent(repositoryId)}/summary`)
        ]);

        let techStack = null;
        if (techRes.status === "fulfilled" && techRes.value.ok) {
            const data = await techRes.value.json();
            techStack = data.technology_stack || {};
        }

        let overview = null;
        if (overviewRes.status === "fulfilled" && overviewRes.value.ok) {
            const data = await overviewRes.value.json();
            overview = data.overview || {};
        }

        let summary = null;
        if (summaryRes.status === "fulfilled" && summaryRes.value.ok) {
            summary = await summaryRes.value.json();
        }

        renderTechStackBadges(techStack, overview);
        if (summary) {
            renderRepositoryInsights(summary);
        }
    } catch (e) {
        console.warn("Could not fetch real-time repository details:", e);
    }
}

function renderRepositoryInsights(summary) {
    const panel = document.getElementById("repoInsightsPanel");
    if (!panel || !summary) return;

    panel.hidden = false;

    // 1. Languages
    const langContainer = document.getElementById("languageBarsContainer");
    const fileCountBadge = document.getElementById("sourceFileCountBadge");
    const langData = summary.language_summary || {};
    const languages = langData.languages || [];

    if (fileCountBadge) {
        fileCountBadge.textContent = `${langData.source_file_count || 0} source files`;
    }

    if (langContainer) {
        langContainer.innerHTML = "";
        const langColors = {
            Python: "#3b82f6",
            TypeScript: "#38bdf8",
            JavaScript: "#facc15",
            HTML: "#f97316",
            CSS: "#ec4899",
            Java: "#ef4444",
            Rust: "#f97316",
            Go: "#06b6d4"
        };

        if (languages.length) {
            languages.slice(0, 5).forEach(l => {
                const item = document.createElement("div");
                item.className = "language-item";
                const color = langColors[l.name] || "#8b5cf6";
                item.innerHTML = `
                    <span class="language-name">
                        <span class="language-dot" style="background: ${color}"></span>
                        ${l.name}
                    </span>
                    <span class="language-count">${l.file_count} files</span>
                `;
                langContainer.appendChild(item);
            });
        } else {
            langContainer.innerHTML = '<span class="helper-text">No languages detected</span>';
        }
    }

    // 2. Dependency Manifests
    const depList = document.getElementById("dependencyManifestList");
    const manifestBadge = document.getElementById("manifestCountBadge");
    const manifests = summary.dependency_manifests || [];

    if (manifestBadge) {
        manifestBadge.textContent = `${manifests.length} manifest${manifests.length === 1 ? '' : 's'}`;
    }

    if (depList) {
        depList.innerHTML = "";
        if (manifests.length) {
            manifests.forEach(m => {
                const card = document.createElement("div");
                card.className = "manifest-card";
                const baseName = m.file.split("/").pop();
                const chips = (m.dependencies || []).slice(0, 6).map(d =>
                    `<span class="dep-chip"><strong>${d.name}</strong> ${d.version !== 'unspecified' ? d.version : ''}</span>`
                ).join("");
                card.innerHTML = `
                    <div class="manifest-header">
                        <i data-lucide="file-text"></i> ${baseName}
                    </div>
                    <div class="manifest-deps">${chips}</div>
                `;
                depList.appendChild(card);
            });
        } else {
            depList.innerHTML = '<span class="helper-text">No dependency manifests found</span>';
        }
    }

    // 3. Safe Environment Inventory
    const envList = document.getElementById("envFileList");
    const envFiles = summary.environment_files || [];

    if (envList) {
        envList.innerHTML = "";
        if (envFiles.length) {
            envFiles.forEach(env => {
                const card = document.createElement("div");
                card.className = "env-card";
                const baseName = env.file.split("/").pop();
                const chips = (env.variable_names || []).map(v =>
                    `<span class="env-var-chip">${v}</span>`
                ).join("");
                card.innerHTML = `
                    <div class="env-file-name">${baseName}</div>
                    <div class="env-vars-container">${chips || '<span class="helper-text">No variables found</span>'}</div>
                `;
                envList.appendChild(card);
            });
        } else {
            envList.innerHTML = '<span class="helper-text">No environment template files detected</span>';
        }
    }

    refreshIcons();
}

function renderTechStackBadges(techStack, overview) {
    const container = document.getElementById("techBadgeContainer");
    const section = document.getElementById("repoTechStack");
    if (!container || !section) return;

    const badges = new Set();
    if (techStack) {
        (techStack.languages || []).forEach(l => badges.add(l));
        (techStack.frameworks || []).forEach(f => badges.add(f));
        (techStack.ai_ml || []).forEach(a => badges.add(a));
        (techStack.databases || []).forEach(d => badges.add(d));
    }
    if (overview && overview.languages) {
        Object.keys(overview.languages).forEach(l => badges.add(l));
    }

    if (badges.size > 0) {
        container.innerHTML = "";
        Array.from(badges).slice(0, 10).forEach(item => {
            const span = document.createElement("span");
            span.className = "tech-badge";
            span.textContent = item;
            container.appendChild(span);
        });
        section.hidden = false;

        const primary = Array.from(badges).slice(0, 3).join(", ");
        const count = currentRepository?.file_count || 0;
        setText("currentRepositoryFileCount", `${count} files · ${primary}`);
    }
}

function initializeChat() {
    const form =
        document.getElementById("chatForm");

    const input =
        document.getElementById("questionInput");

    const sendButton =
        document.getElementById("sendButton");

    if (!form || !input) return;

    form.addEventListener(
        "submit",
        async event => {
            event.preventDefault();

            const question =
                input.value.trim();

            if (!question || isBusy) {
                return;
            }

            await askCodeLens(
                question,
                input,
                sendButton
            );
        }
    );
}

async function askCodeLens(
    question,
    input,
    sendButton
) {
    const repository =
        currentRepository ||
        loadCurrentRepository();

    if (!repository?.repository_id) {
        showToast(
            "Upload a repository before asking questions.",
            true
        );
        return;
    }

    if (isBusy) {
        return;
    }

    isBusy = true;

    if (sendButton) {
        sendButton.disabled = true;
    }

    appendUserMessage(question);

    input.value = "";

    resizeTextarea(input);

    const thinking =
        appendThinkingMessage();

    const MAX_RETRIES = 2; // Up to 3 attempts (initial + 2 retries)
    const RETRY_DELAYS = [3000, 6000];
    let finalOutcome = null;

    try {
        for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            let response = null;
            let data = null;
            let fetchError = null;

            const controller = new AbortController();
            // 45s timeout per attempt to accommodate Render container wake-up latency
            const timeoutId = setTimeout(() => controller.abort(), 45000);

            try {
                response = await fetch(
                    `${CODELENS_API_BASE}/api/repositories/${encodeURIComponent(repository.repository_id)}/ask`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            question,
                            top_k: 5
                        }),
                        signal: controller.signal
                    }
                );
                data = await readApiResponse(response);
            } catch (err) {
                fetchError = err;
            } finally {
                clearTimeout(timeoutId);
            }

            // 1. Success
            if (response && response.ok) {
                thinking.remove();

                appendAssistantMessage(
                    data.answer ||
                    "I couldn't find enough evidence in the uploaded repository."
                );

                updateSourcesSection(
                    data.sources || [],
                    data.retrieved_chunks || []
                );

                addConversationToHistory(
                    repository.repository_id,
                    repository.name,
                    question
                );

                return;
            }

            // 2. Repository not found on server (404)
            if (response && response.status === 404) {
                clearCurrentRepository();
                thinking.remove();
                const categorized = categorizeError(null, response, data);
                appendErrorMessage(categorized.message, categorized.hint);
                return;
            }

            // 3. Client errors (400, 422)
            if (response && (response.status === 400 || response.status === 422)) {
                thinking.remove();
                const categorized = categorizeError(null, response, data);
                appendErrorMessage(categorized.message, categorized.hint);
                return;
            }

            // 4. Cold start / Network error (TypeError, timeout, 502, 503, 504)
            const isColdStart = fetchError || (response && (response.status === 502 || response.status === 503 || response.status === 504));

            if (isColdStart && attempt < MAX_RETRIES) {
                const delayMs = RETRY_DELAYS[attempt] || 4000;
                const seconds = Math.round(delayMs / 1000);

                const bubble = thinking ? thinking.querySelector(".message-bubble") : null;
                if (bubble) {
                    bubble.innerHTML = `
                        <div style="display: inline-flex; align-items: center; gap: 8px;">
                            <i data-lucide="loader-circle" class="codelens-spinner"></i>
                            <span>CodeLens backend is waking up (cold start)... Retrying in ${seconds}s (attempt ${attempt + 1}/${MAX_RETRIES})</span>
                        </div>
                    `;
                    refreshIcons();
                }

                await new Promise(resolve => setTimeout(resolve, delayMs));
                continue;
            }

            // All attempts exhausted or other server error
            finalOutcome = { error: fetchError, response, data };
            break;
        }

        thinking.remove();
        const categorized = categorizeError(
            finalOutcome?.error,
            finalOutcome?.response,
            finalOutcome?.data
        );
        appendErrorMessage(categorized.message, categorized.hint);

        console.error("CodeLens request failed:", finalOutcome);

    } catch (unhandled) {
        thinking.remove();
        const categorized = categorizeError(unhandled, null, null);
        appendErrorMessage(categorized.message, categorized.hint);
        console.error("Unhandled CodeLens chat error:", unhandled);

    } finally {
        isBusy = false;

        if (sendButton) {
            sendButton.disabled = false;
        }

        scrollChatToBottom();
    }
}

function getChatMessages() {
    return document.getElementById(
        "chatMessages"
    );
}

function appendUserMessage(question) {
    const container =
        getChatMessages();

    if (!container) return;

    const article =
        document.createElement(
            "article"
        );

    article.className =
        "chat-message user-message";

    article.innerHTML = `
        <div class="message-avatar">S</div>
        <div class="message-content">
            <div class="message-role">You</div>
            <div class="message-bubble">${escapeHtml(question)}</div>
        </div>
    `;

    container.appendChild(article);
}

function appendThinkingMessage() {
    const container =
        getChatMessages();

    const article =
        document.createElement(
            "article"
        );

    article.className =
        "chat-message assistant-message thinking-message";

    article.innerHTML = `
        <div class="assistant-avatar"><span></span></div>
        <div class="message-content">
            <div class="message-role">CodeLens Assistant</div>
            <div class="message-bubble">
                Thinking about your repository...
            </div>
        </div>
    `;

    if (container) {
        container.appendChild(article);
    }

    scrollChatToBottom();

    return article;
}

function appendAssistantMessage(answer) {
    const container =
        getChatMessages();

    if (!container) return;
        const article =
        document.createElement(
            "article"
        );

    article.className =
        "chat-message assistant-message";

    article.innerHTML = `
        <div class="assistant-avatar"><span></span></div>
        <div class="message-content">
            <div class="message-role">CodeLens Assistant</div>
            <div class="message-bubble assistant-answer">
                ${formatAnswer(answer)}
            </div>
        </div>
    `;

    container.appendChild(article);

    scrollChatToBottom();
}

function appendErrorMessage(message, hint = null) {
    const container =
        getChatMessages();

    if (!container) return;

    const article =
        document.createElement(
            "article"
        );

    article.className =
        "chat-message assistant-message";

    const hintHtml = hint
        ? `<div class="assistant-error-hint">${escapeHtml(hint)}</div>`
        : "";

    article.innerHTML = `
        <div class="assistant-avatar"><span></span></div>
        <div class="message-content">
            <div class="message-role">CodeLens Assistant</div>
            <div class="message-bubble assistant-error">
                ${escapeHtml(message)}
                ${hintHtml}
            </div>
        </div>
    `;

    container.appendChild(article);

    scrollChatToBottom();
}

function formatAnswer(answer) {
    const safe =
        escapeHtml(answer);

    const parts =
        safe.split(/```/);

    return parts
        .map((part, index) => {
            if (index % 2 === 1) {
                const lines =
                    part.split("\n");

                if (
                    lines[0] &&
                    /^[a-zA-Z0-9_+#.-]+$/.test(
                        lines[0].trim()
                    )
                ) {
                    lines.shift();
                }

                return `
                    <pre class="assistant-code">
                        <code>${lines.join("\n")}</code>
                    </pre>
                `;
            }

            return part
                .split(/\n\n+/)
                .map(
                    paragraph =>
                        paragraph.trim()
                            ? `<p>${paragraph.replace(
                                /\n/g,
                                "<br>"
                            )}</p>`
                            : ""
                )
                .join("");
        })
        .join("");
}

function scrollChatToBottom() {
    const container =
        getChatMessages();

    if (!container) return;

    window.requestAnimationFrame(() => {
        container.scrollTop =
            container.scrollHeight;
    });
}

function initializeSuggestions() {
    document.querySelectorAll(
        "[data-question], .suggestion-card, .prompt-card"
    ).forEach(element => {
        element.addEventListener(
            "click",
            () => {
                const input =
                    document.getElementById(
                        "questionInput"
                    );

                if (!input) return;

                const question =
                    element.dataset.question ||
                    element
                        .querySelector("strong")
                        ?.textContent
                        ?.trim() ||
                    element.textContent.trim();

                if (!question) return;

                input.value =
                    question.replace(
                        /[“”]/g,
                        ""
                    );

                input.focus();

                resizeTextarea(input);
            }
        );
    });
}

function initializeTextarea() {
    const input =
        document.getElementById(
            "questionInput"
        );

    if (!input) return;

    input.addEventListener(
        "input",
        () => resizeTextarea(input)
    );

    input.addEventListener(
        "keydown",
        event => {
            if (
                event.key === "Enter" &&
                !event.shiftKey
            ) {
                event.preventDefault();

                document
                    .getElementById("chatForm")
                    ?.requestSubmit();
            }
        }
    );
}

function resizeTextarea(input) {
    input.style.height = "auto";

    input.style.height =
        `${Math.min(
            input.scrollHeight,
            180
        )}px`;
}

function updateRepositoryUI(repository) {
    if (!repository) return;

    currentRepository =
        repository;

    saveCurrentRepository(
        repository
    );

    const name =
        repository.name ||
        "Repository";

    const count =
        Number(
            repository.file_count ||
            repository.files?.length ||
            0
        );

    setText(
        "currentRepositoryName",
        name
    );

    setText(
        "currentRepositoryFileCount",
        `${count} files`
    );

    setText(
        "breadcrumbRepositoryName",
        name
    );

    setText(
        "heroRepositoryName",
        name
    );

    setText(
        "heroRepositoryFileCount",
        count
    );

    setText(
        "fileCount",
        count
    );

    setText(
        "repositoryStatusText",
        "Repository ready"
    );

    renderRepositoryFiles(
        repository.files || []
    );

    renderHistory();

    if (repository.repository_id) {
        fetchAndRenderRepositoryDetails(repository.repository_id);
    }
}

function setText(id, value) {
    const element =
        document.getElementById(id);

    if (element) {
        element.textContent = value;
    }
}

function renderRepositoryFiles(files) {
    const tree =
        document.getElementById(
            "repositoryFileTree"
        );

    if (!tree) return;

    tree.innerHTML = "";

    if (!files.length) {
        tree.innerHTML =
            '<p class="history-empty">No files found.</p>';

        return;
    }
        const folders =
        new Map();

    files.forEach(filePath => {
        const normalized =
            String(filePath)
                .replace(/\\/g, "/");

        const parts =
            normalized
                .split("/")
                .filter(Boolean);

        if (parts.length === 1) {
            tree.appendChild(
                createTreeFile(
                    normalized
                )
            );

            return;
        }

        const folder =
            parts[0];

        if (!folders.has(folder)) {
            folders.set(
                folder,
                []
            );
        }

        folders
            .get(folder)
            .push(normalized);
    });

    folders.forEach(
        (folderFiles, folderName) => {
            const folderButton =
                document.createElement(
                    "button"
                );

            folderButton.className =
                "tree-folder";

            folderButton.type =
                "button";

            folderButton.innerHTML = `
                <i data-lucide="chevron-down"></i>
                <i data-lucide="folder"></i>
                <span>${escapeHtml(folderName)}</span>
            `;

            const children =
                document.createElement(
                    "div"
                );

            children.className =
                "tree-children";

            folderFiles.forEach(
                filePath => {
                    children.appendChild(
                        createTreeFile(
                            filePath
                        )
                    );
                }
            );

            folderButton.addEventListener(
                "click",
                () => {
                    children.classList.toggle(
                        "collapsed"
                    );

                    folderButton.classList.toggle(
                        "collapsed"
                    );
                }
            );

            tree.appendChild(
                folderButton
            );

            tree.appendChild(
                children
            );
        }
    );

    refreshIcons();
}

function createTreeFile(filePath) {
    const button =
        document.createElement(
            "button"
        );

    button.className =
        "tree-file";

    button.type =
        "button";

    button.innerHTML = `
        <i data-lucide="file-code-2"></i>
        <span title="${escapeHtml(filePath)}">
            ${escapeHtml(
                filePath.split("/").pop()
            )}
        </span>
    `;

    button.addEventListener(
        "click",
        () => showToast(filePath)
    );

    return button;
}

function updateSourcesSection(
    sources,
    retrievedChunks
) {
    const grid =
        document.getElementById(
            "sourceGrid"
        );

    const count =
        document.getElementById(
            "sourceCount"
        );

    if (!grid) return;

    const normalized =
        normalizeSources(
            sources,
            retrievedChunks
        );

    if (count) {
        count.textContent =
            `${normalized.length} relevant file${
                normalized.length === 1
                    ? ""
                    : "s"
            }`;
    }

    if (!normalized.length) {
        grid.innerHTML =
            '<p class="history-empty">No source files were returned.</p>';

        return;
    }

    grid.innerHTML =
        normalized
            .map(
                source => `
                    <article class="source-card">
                        <div class="source-top">
                            <div class="source-file-icon python">
                                <i data-lucide="file-code-2"></i>
                            </div>

                            <div class="source-file">
                                <strong>
                                    ${escapeHtml(
                                        source.file
                                    )}
                                </strong>

                                <span>
                                    ${escapeHtml(
                                        source.type ||
                                        source.name ||
                                        "Repository source"
                                    )}
                                </span>
                            </div>
                        </div>

                        <div class="source-lines">
                            ${escapeHtml(
                                source.lines ||
                                "Relevant code"
                            )}
                        </div>

                        <div class="code-preview">
                            ${escapeHtml(
                                source.preview ||
                                "Relevant repository context was retrieved for this answer."
                            )}
                        </div>
                    </article>
                `
            )
            .join("");

    refreshIcons();
}

function normalizeSources(
    sources,
    chunks
) {
    const items =
        Array.isArray(sources)
            ? sources
            : [];

    const chunkItems =
        Array.isArray(chunks)
            ? chunks
            : [];

    const result = [];
    const seen = new Set();

    items.forEach(item => {
        const metadata =
            item?.metadata ||
            item ||
            {};

        const file =
            metadata.file_path ||
            metadata.file ||
            item.file_path ||
            "Unknown file";

        if (seen.has(file)) {
            return;
        }

        seen.add(file);

        result.push({
            file,

            type:
                metadata.chunk_type ||
                metadata.language ||
                "Source",

            lines:
                metadata.start_line &&
                metadata.end_line
                    ? `Lines ${metadata.start_line}–${metadata.end_line}`
                    : "Relevant code",

            preview:
                item.content ||
                metadata.content ||
                "Relevant repository context."
        });
    });

    chunkItems.forEach(item => {
        const metadata =
            item?.metadata ||
            {};

        const file =
            metadata.file_path ||
            "Unknown file";

        if (seen.has(file)) {
            return;
        }

        seen.add(file);

        result.push({
            file,

            type:
                metadata.chunk_type ||
                metadata.language ||
                "Source",

            lines:
                metadata.start_line &&
                metadata.end_line
                    ? `Lines ${metadata.start_line}–${metadata.end_line}`
                    : "Retrieved chunk",

            preview:
                item.content ||
                "Retrieved repository context."
        });
    });

    return result.slice(
        0,
        6
    );
}
function getHistory() {
    try {
        const value =
            localStorage.getItem(
                HISTORY_KEY
            );

        return value
            ? JSON.parse(value)
            : {
                repositories: [],
                conversations: []
            };

    } catch (_) {
        return {
            repositories: [],
            conversations: []
        };
    }
}

function saveHistory(history) {
    localStorage.setItem(
        HISTORY_KEY,
        JSON.stringify(history)
    );
}

function addRepositoryToHistory(
    repository
) {
    const history =
        getHistory();

    const item = {
        repository_id:
            repository.repository_id,

        name:
            repository.name,

        file_count:
            repository.file_count ||
            repository.files?.length ||
            0,

        files:
            repository.files ||
            [],

        updated_at:
            Date.now()
    };

    history.repositories = [
        item,

        ...history.repositories.filter(
            r =>
                r.repository_id !==
                item.repository_id
        )
    ].slice(0, 10);

    saveHistory(history);

    renderHistory();
}

function addConversationToHistory(
    repositoryId,
    repositoryName,
    question
) {
    const history =
        getHistory();

    const item = {
        id:
            `${Date.now()}-${Math.random()
                .toString(36)
                .slice(2, 8)}`,

        repository_id:
            repositoryId,

        repository_name:
            repositoryName,

        question,

        created_at:
            Date.now()
    };

    history.conversations = [
        item,
        ...history.conversations
    ].slice(0, 20);

    saveHistory(history);

    renderHistory();
}

function initializeHistory() {
    renderHistory();

    const clearButton =
        document.getElementById(
            "clearHistoryButton"
        );

    if (clearButton) {
        clearButton.addEventListener(
            "click",
            () => {
                localStorage.removeItem(
                    HISTORY_KEY
                );

                renderHistory();

                showToast(
                    "History cleared."
                );
            }
        );
    }
}

function renderHistory() {
    const list =
        document.getElementById(
            "historyList"
        );

    const empty =
        document.getElementById(
            "historyEmpty"
        );

    if (!list) return;

    const history =
        getHistory();

    if (
        !history.repositories.length &&
        !history.conversations.length
    ) {
        list.innerHTML = "";

        if (empty) {
            empty.hidden = false;
        }

        return;
    }

    if (empty) {
        empty.hidden = true;
    }

    list.innerHTML = "";

    history.repositories
        .slice(0, 5)
        .forEach(repository => {
            const button =
                document.createElement(
                    "button"
                );

            button.className =
                "history-item";

            button.type =
                "button";

            button.innerHTML = `
                <span class="history-icon repository-history-icon">
                    <i data-lucide="box"></i>
                </span>

                <span class="history-info">
                    <strong>
                        ${escapeHtml(
                            repository.name
                        )}
                    </strong>

                    <small>
                        Repository · ${
                            repository.file_count ||
                            0
                        } files
                    </small>
                </span>

                <i
                    class="history-arrow"
                    data-lucide="chevron-right"
                ></i>
            `;

            button.addEventListener(
                "click",
                () =>
                    openRepositoryFromHistory(
                        repository
                    )
            );

            list.appendChild(
                button
            );
        });

    history.conversations
        .slice(0, 5)
        .forEach(conversation => {
            const button =
                document.createElement(
                    "button"
                );

            button.className =
                "history-item";

            button.type =
                "button";

            button.innerHTML = `
                <span class="history-icon conversation-history-icon">
                    <i data-lucide="message-square"></i>
                </span>

                <span class="history-info">
                    <strong>
                        ${escapeHtml(
                            conversation.question
                        )}
                    </strong>

                    <small>
                        ${escapeHtml(
                            conversation.repository_name
                        )}
                        · Conversation
                    </small>
                </span>

                <i
                    class="history-arrow"
                    data-lucide="chevron-right"
                ></i>
            `;

            button.addEventListener(
                "click",
                () =>
                    openConversationFromHistory(
                        conversation
                    )
            );

            list.appendChild(
                button
            );
        });

    refreshIcons();
}

function openRepositoryFromHistory(
    repository
) {
    saveCurrentRepository(
        repository
    );

    updateRepositoryUI(
        repository
    );

    showToast(
        `${repository.name} selected.`
    );
}

function openConversationFromHistory(
    conversation
) {
    const repository =
        getHistory()
            .repositories
            .find(
                item =>
                    item.repository_id ===
                    conversation.repository_id
            );

    if (repository) {
        saveCurrentRepository(
            repository
        );

        updateRepositoryUI(
            repository
        );
    }

    const input =
        document.getElementById(
            "questionInput"
        );

    if (input) {
        input.value =
            conversation.question;

        input.focus();

        resizeTextarea(
            input
        );
    }
}

// ============================================================
// FIREBASE AUTHENTICATION UI INTEGRATION
// ============================================================

function initializeFirebaseAuth() {
    const authModal = document.getElementById("authModal");
    const closeAuthModal = document.getElementById("closeAuthModal");
    const topbarSignInBtn = document.getElementById("topbarSignInBtn");
    const userMenuWrapper = document.getElementById("userMenuWrapper");
    const topbarAvatarButton = document.getElementById("topbarAvatarButton");
    const topbarAvatarInitial = document.getElementById("topbarAvatarInitial");
    const userDropdownMenu = document.getElementById("userDropdownMenu");
    const dropdownUserName = document.getElementById("dropdownUserName");
    const dropdownUserEmail = document.getElementById("dropdownUserEmail");
    const dropdownLogoutBtn = document.getElementById("dropdownLogoutBtn");
    const sidebarUserCard = document.getElementById("sidebarUserCard");
    const sidebarUserAvatar = document.getElementById("sidebarUserAvatar");
    const sidebarUserName = document.getElementById("sidebarUserName");
    const sidebarUserEmail = document.getElementById("sidebarUserEmail");
    const sidebarAuthActionBtn = document.getElementById("sidebarAuthActionBtn");

    const authTabs = document.getElementById("authTabs");
    const tabAuthSignIn = document.getElementById("tabAuthSignIn");
    const tabAuthRegister = document.getElementById("tabAuthRegister");
    const authModalTitle = document.getElementById("authModalTitle");
    const authModalSubtitle = document.getElementById("authModalSubtitle");
    const googleSignInBtn = document.getElementById("googleSignInBtn");
    const authForm = document.getElementById("authForm");
    const authEmail = document.getElementById("authEmail");
    const authPassword = document.getElementById("authPassword");
    const passwordHint = document.getElementById("passwordHint");
    const authSubmitBtn = document.getElementById("authSubmitBtn");
    const authSubmitText = document.getElementById("authSubmitText");
    const authErrorAlert = document.getElementById("authErrorAlert");
    const authErrorText = document.getElementById("authErrorText");

    let currentAuthMode = "signin"; // "signin" or "register"

    function openModal(mode = "signin") {
        setAuthMode(mode);
        hideError();
        if (authForm) authForm.reset();
        if (authModal) {
            authModal.classList.add("visible");
            authModal.setAttribute("aria-hidden", "false");
        }
    }

    function closeModal() {
        if (authModal) {
            authModal.classList.remove("visible");
            authModal.setAttribute("aria-hidden", "true");
        }
        hideError();
    }

    function setAuthMode(mode) {
        currentAuthMode = mode;
        if (tabAuthSignIn && tabAuthRegister) {
            tabAuthSignIn.classList.toggle("active", mode === "signin");
            tabAuthRegister.classList.toggle("active", mode === "register");
        }
        if (authModalTitle) {
            authModalTitle.textContent = mode === "signin" ? "Welcome to CodeLens" : "Create an Account";
        }
        if (authModalSubtitle) {
            authModalSubtitle.textContent = mode === "signin"
                ? "Sign in to save your sessions and access repository intelligence."
                : "Get started with AI-driven codebase understanding.";
        }
        if (authSubmitText) {
            authSubmitText.textContent = mode === "signin" ? "Sign In" : "Create Account";
        }
        if (passwordHint) {
            passwordHint.hidden = mode !== "register";
        }
        hideError();
    }

    function showError(msg) {
        if (authErrorAlert && authErrorText) {
            authErrorText.textContent = msg;
            authErrorAlert.hidden = false;
        }
    }

    function hideError() {
        if (authErrorAlert) {
            authErrorAlert.hidden = true;
        }
    }

    // Modal Triggers
    if (topbarSignInBtn) {
        topbarSignInBtn.addEventListener("click", () => { window.location.href = "login.html"; });
    }
    if (sidebarUserCard) {
        sidebarUserCard.addEventListener("click", (e) => {
            if (e.target.closest("#sidebarAuthActionBtn")) return;
            const currentUser = window.CodeLensAuth ? window.CodeLensAuth.getCurrentUser() : null;
            if (!currentUser) {
                window.location.href = "login.html";
            } else if (userDropdownMenu) {
                userDropdownMenu.hidden = !userDropdownMenu.hidden;
            }
        });
    }
    if (closeAuthModal) {
        closeAuthModal.addEventListener("click", closeModal);
    }
    if (authModal) {
        authModal.addEventListener("click", (e) => {
            if (e.target === authModal) closeModal();
        });
    }
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && authModal && authModal.classList.contains("visible")) {
            closeModal();
        }
    });

    // Tab Switching
    if (tabAuthSignIn) {
        tabAuthSignIn.addEventListener("click", () => setAuthMode("signin"));
    }
    if (tabAuthRegister) {
        tabAuthRegister.addEventListener("click", () => setAuthMode("register"));
    }

    // Topbar Avatar Menu Toggle
    if (topbarAvatarButton && userDropdownMenu) {
        topbarAvatarButton.addEventListener("click", (e) => {
            e.stopPropagation();
            userDropdownMenu.hidden = !userDropdownMenu.hidden;
        });
        document.addEventListener("click", (e) => {
            if (!e.target.closest("#userMenuWrapper")) {
                userDropdownMenu.hidden = true;
            }
        });
    }

    // Form Submit (Email & Password)
    if (authForm) {
        authForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            hideError();

            const email = (authEmail ? authEmail.value : "").trim();
            const password = (authPassword ? authPassword.value : "").trim();

            if (!email || !password) {
                showError("Please enter both email and password.");
                return;
            }

            if (authSubmitBtn) {
                authSubmitBtn.disabled = true;
                if (authSubmitText) authSubmitText.textContent = "Processing...";
            }

            try {
                if (!window.CodeLensAuth) {
                    showError("Authentication service is initializing. Please try again.");
                    return;
                }

                let res;
                if (currentAuthMode === "register") {
                    res = await window.CodeLensAuth.registerUser(email, password);
                } else {
                    res = await window.CodeLensAuth.loginUser(email, password);
                }

                if (res && res.success) {
                    closeModal();
                    const name = res.user.displayName || res.user.email || "User";
                    showToast(currentAuthMode === "register" ? `Account created! Welcome, ${name}` : `Welcome back, ${name}`);
                } else {
                    showError(res ? res.error : "Authentication failed.");
                }
            } catch (err) {
                showError(err.message || "An unexpected authentication error occurred.");
            } finally {
                if (authSubmitBtn) {
                    authSubmitBtn.disabled = false;
                    if (authSubmitText) {
                        authSubmitText.textContent = currentAuthMode === "signin" ? "Sign In" : "Create Account";
                    }
                }
            }
        });
    }

    // Google Sign-In
    if (googleSignInBtn) {
        googleSignInBtn.addEventListener("click", async () => {
            hideError();
            googleSignInBtn.disabled = true;

            try {
                if (!window.CodeLensAuth) {
                    showError("Authentication service is initializing. Please try again.");
                    return;
                }

                const res = await window.CodeLensAuth.googleLogin();
                if (res && res.success) {
                    closeModal();
                    const name = res.user.displayName || res.user.email || "User";
                    showToast(`Signed in with Google as ${name}`);
                } else {
                    showError(res ? res.error : "Google sign-in failed.");
                }
            } catch (err) {
                showError(err.message || "Google sign-in failed.");
            } finally {
                googleSignInBtn.disabled = false;
            }
        });
    }

    // Logout Action
    const handleLogout = async () => {
        if (!window.CodeLensAuth) return;
        if (userDropdownMenu) userDropdownMenu.hidden = true;
        await window.CodeLensAuth.logoutUser();
        window.location.replace("login.html");
    };

    if (dropdownLogoutBtn) {
        dropdownLogoutBtn.addEventListener("click", handleLogout);
    }
    if (sidebarAuthActionBtn) {
        sidebarAuthActionBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            handleLogout();
        });
    }

    // Auth State Observer (Enforces Sign-in Requirement)
    const updateUIForUser = (user) => {
        const authGuardCurtain = document.getElementById("authGuardCurtain");

        if (user) {
            // User authenticated: Mark authenticated & lift the curtain
            window._codelensUserAuthenticated = true;
            if (window._authTimeout) clearTimeout(window._authTimeout);

            if (authGuardCurtain) {
                authGuardCurtain.style.opacity = "0";
                authGuardCurtain.style.pointerEvents = "none";
                setTimeout(() => {
                    if (authGuardCurtain && authGuardCurtain.parentNode) {
                        authGuardCurtain.parentNode.removeChild(authGuardCurtain);
                    }
                }, 320);
            }

            const displayName = user.displayName || (user.email ? user.email.split("@")[0] : "User");
            const initial = displayName.charAt(0).toUpperCase();

            if (topbarSignInBtn) topbarSignInBtn.style.display = "none";
            if (userMenuWrapper) {
                userMenuWrapper.hidden = false;
                userMenuWrapper.style.display = "inline-block";
            }
            if (userMenuWrapper) userMenuWrapper.hidden = false;
            if (topbarAvatarInitial) topbarAvatarInitial.textContent = initial;

            if (dropdownUserName) dropdownUserName.textContent = displayName;
            if (dropdownUserEmail) dropdownUserEmail.textContent = user.email || "";

            if (sidebarUserName) sidebarUserName.textContent = displayName;
            if (sidebarUserEmail) sidebarUserEmail.textContent = user.email || "Authenticated";
            if (sidebarAuthActionBtn) sidebarAuthActionBtn.hidden = false;
            if (sidebarUserAvatar) sidebarUserAvatar.textContent = initial;
        } else {
            // User not authenticated: Web application will NOT open until signed in
            window._codelensUserAuthenticated = false;
            window.location.replace("login.html");
            return;
        }
        if (typeof lucide !== "undefined") lucide.createIcons();
    };

    if (window.CodeLensAuth && typeof window.CodeLensAuth.onAuthChange === "function") {
        window.CodeLensAuth.onAuthChange(updateUIForUser);
    } else {
        const interval = setInterval(() => {
            if (window.CodeLensAuth && typeof window.CodeLensAuth.onAuthChange === "function") {
                clearInterval(interval);
                window.CodeLensAuth.onAuthChange(updateUIForUser);
            }
        }, 100);
        setTimeout(() => clearInterval(interval), 5000);
    }
}
