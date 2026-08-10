(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────────────────────────
    var API_BASE = '/api';

    // ── State ──────────────────────────────────────────────────────────────────
    var token = localStorage.getItem('token');
    var currentUser = null;
    var isGuest = false;
    var currentConversationId = null;
    var guestConversations = [];      // In-memory guest conversations (session only)
    var activeConversations = [];     // Active conversation list (DB or guest)
    var isStreaming = false;          // Track if we're currently streaming a response
    var abortController = null;       // For cancelling fetch requests
    var appSessionVersion = 0;        // Guards against stale async init overwriting newer state

    // ── DOM References ─────────────────────────────────────────────────────────
    var welcomeContainer = document.getElementById('welcomeContainer');
    var authContainer    = document.getElementById('authContainer');
    var chatContainer    = document.getElementById('chatContainer');
    var authError        = document.getElementById('authError');
    var loginForm        = document.getElementById('loginForm');
    var registerForm     = document.getElementById('registerForm');
    var conversationsList = document.getElementById('conversationsList');
    var messagesContainer = document.getElementById('messagesContainer');
    var emptyState       = document.getElementById('emptyState');
    var messageInput     = document.getElementById('messageInput');
    var sendBtn          = document.getElementById('sendBtn');
    var chatInputBox     = document.getElementById('chatInputBox');
    var mainChat         = document.getElementById('mainChat');
    var userEmail        = document.getElementById('userEmail');
    var userAvatar       = document.getElementById('userAvatar');
    var newChatBtn       = document.getElementById('newChatBtn');
    var logoutBtn        = document.getElementById('logoutBtn');
    var guestBanner      = document.getElementById('guestBanner');
    var bannerSignupBtn  = document.getElementById('bannerSignupBtn');
    var bannerDismissBtn = document.getElementById('bannerDismissBtn');
    var googleLoginBtn   = document.getElementById('googleLoginBtn');
    var welcomeGuestBtn  = document.getElementById('welcomeGuestBtn');
    var welcomeLoginBtn  = document.getElementById('welcomeLoginBtn');
    var backToWelcome    = document.getElementById('backToWelcome');
    var passwordMismatch = document.getElementById('passwordMismatch');
    var sidebar          = document.getElementById('sidebar');
    var sidebarToggle    = document.getElementById('sidebarToggle');
    var sidebarBackdrop  = document.getElementById('sidebarBackdrop');
    var settingsBtn      = document.getElementById('settingsBtn');
    var mobileMenuBtn    = document.getElementById('mobileMenuBtn');
    var userInfo         = document.getElementById('userInfo');
    var userSub          = document.getElementById('userSub');
    var guestLoginBtn    = document.getElementById('guestLoginBtn');
    var accountPopup     = document.getElementById('accountPopup');
    var profileModal     = document.getElementById('profileModal');
    var profileCloseBtn  = document.getElementById('profileCloseBtn');
    var profilePhotoPreview = document.getElementById('profilePhotoPreview');
    var profilePhotoBtn  = document.getElementById('profilePhotoBtn');
    var profilePhotoRemoveBtn = document.getElementById('profilePhotoRemoveBtn');
    var profilePhotoInput = document.getElementById('profilePhotoInput');
    var profileDisplayName = document.getElementById('profileDisplayName');
    var profileError     = document.getElementById('profileError');
    var profileCancelBtn = document.getElementById('profileCancelBtn');
    var profileSaveBtn   = document.getElementById('profileSaveBtn');
    var deleteConfirm    = document.getElementById('deleteConfirm');
    var deleteConfirmClose = document.getElementById('deleteConfirmClose');
    var deleteConfirmCancel = document.getElementById('deleteConfirmCancel');
    var deleteConfirmYes = document.getElementById('deleteConfirmYes');
    var renameModal      = document.getElementById('renameModal');
    var renameCloseBtn   = document.getElementById('renameCloseBtn');
    var renameInput      = document.getElementById('renameInput');
    var renameCancelBtn  = document.getElementById('renameCancelBtn');
    var renameConfirmBtn = document.getElementById('renameConfirmBtn');
    var renameError      = document.getElementById('renameError');
    var logoutConfirm    = document.getElementById('logoutConfirm');
    var logoutConfirmClose = document.getElementById('logoutConfirmClose');
    var logoutConfirmNo  = document.getElementById('logoutConfirmNo');
    var logoutConfirmYes = document.getElementById('logoutConfirmYes');

    // ── Streaming Configuration ────────────────────────────────────────────────
    var streamingEnabled = false;

    // Check if streaming is enabled on the server
    async function checkStreamingConfig() {
        try {
            var config = await api('/config');
            streamingEnabled = config.streaming_enabled || false;
        } catch (err) {
            console.warn('Could not fetch streaming config, defaulting to false');
            streamingEnabled = false;
        }
    }

    // ── Auth Tab Switching ─────────────────────────────────────────────────────
    document.querySelectorAll('.auth-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
            document.querySelectorAll('.auth-tab').forEach(function (t) {
                t.classList.remove('active');
            });
            document.querySelectorAll('.auth-form').forEach(function (f) {
                f.classList.remove('active');
            });
            tab.classList.add('active');
            var form = document.getElementById(tab.dataset.tab + 'Form');
            if (form) form.classList.add('active');
        });
    });

    // ── Sidebar (expand / collapse / mobile drawer) ──────────────────────────
    var COLLAPSE_KEY = 'julibot_sidebar_collapsed';

    function isMobileView() {
        return window.matchMedia('(max-width: 768px)').matches;
    }

    // Restore persisted collapsed state (desktop only — CSS ignores it on mobile)
    if (localStorage.getItem(COLLAPSE_KEY) === '1') {
        sidebar.classList.add('collapsed');
    }

    sidebarToggle.addEventListener('click', function () {
        closeAccountPopup();
        if (isMobileView()) {
            closeSidebarDrawer();
        } else {
            var collapsed = sidebar.classList.toggle('collapsed');
            localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
        }
        updateAvatarInteractivity();
    });

    function openSidebarDrawer() {
        sidebar.classList.add('sidebar-open');
        sidebarBackdrop.classList.add('show');
    }

    function closeSidebarDrawer() {
        sidebar.classList.remove('sidebar-open');
        sidebarBackdrop.classList.remove('show');
    }

    if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', openSidebarDrawer);
    if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebarDrawer);

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            closeSidebarDrawer();
            closeAccountPopup();
            closeProfileModal();
            closeDeleteConfirm();
            closeRenameModal();
            closeLogoutConfirm();
        }
    });

    window.addEventListener('resize', function () {
        if (!isMobileView()) closeSidebarDrawer();
    });

    // ── Lightweight toast ─────────────────────────────────────────────────────
    var toastEl = null;
    function showToast(message) {
        if (!toastEl) {
            toastEl = document.createElement('div');
            toastEl.className = 'toast';
            document.body.appendChild(toastEl);
        }
        toastEl.textContent = message;
        toastEl.classList.add('show');
        clearTimeout(showToast._timer);
        showToast._timer = setTimeout(function () {
            toastEl.classList.remove('show');
        }, 2500);
    }

    settingsBtn.addEventListener('click', function () {
        showToast('Settings panel coming soon');
    });

    // ── Helpers ────────────────────────────────────────────────────────────────
    function showError(message) {
        authError.textContent = message;
        authError.classList.add('show');
        setTimeout(function () { authError.classList.remove('show'); }, 5000);
    }

    function escapeHtml(text) {
        var d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }

    function generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
    }

    // Simple markdown-like rendering for code blocks
    function renderContent(content) {
        // Escape HTML first
        var escaped = escapeHtml(content);

        // Protect code blocks so the markdown processing below can't touch
        // their contents (e.g. "#" comments must not be stripped as headings)
        var blocks = [];
        escaped = escaped.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
            blocks.push({ lang: lang, code: code.trim() });
            return '\u0000' + (blocks.length - 1) + '\u0000';
        });

        // Remove markdown heading markers (e.g. "### ") but keep the text
        escaped = escaped.replace(/^#{1,6}\s+/gm, '');

        // Convert inline code
        escaped = escaped.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

        // Convert bold
        escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Convert italic
        escaped = escaped.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Convert newlines to <br>
        escaped = escaped.replace(/\n/g, '<br>');

        // Restore code blocks with an individual copy button on each
        escaped = escaped.replace(/\u0000(\d+)\u0000/g, function(match, index) {
            var b = blocks[parseInt(index, 10)];
            return '<div class="code-block-wrap">' +
                '<button class="code-copy-btn" type="button" title="Copy code" aria-label="Copy code">' +
                    COPY_ICON + '<span class="copy-btn-label">Copy</span>' +
                '</button>' +
                '<pre class="code-block"><code class="language-' + b.lang + '">' + b.code + '</code></pre>' +
            '</div>';
        });

        return escaped;
    }

    // ── Copy code block button ─────────────────────────────────────────────────
    var COPY_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';

    function copyToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise(function (resolve, reject) {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try {
                document.execCommand('copy');
                resolve();
            } catch (err) {
                reject(err);
            }
            document.body.removeChild(ta);
        });
    }

    // Copy the code from whichever code block's button was clicked
    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.code-copy-btn') : null;
        if (!btn) return;
        var wrap = btn.closest('.code-block-wrap');
        var codeEl = wrap ? wrap.querySelector('code') : null;
        var text = codeEl ? codeEl.textContent : '';
        var label = btn.querySelector('.copy-btn-label');
        copyToClipboard(text).then(function () {
            btn.classList.add('copied');
            if (label) label.textContent = 'Copied!';
        }, function () {
            if (label) label.textContent = 'Failed';
        });
        setTimeout(function () {
            if (label) label.textContent = 'Copy';
            btn.classList.remove('copied');
        }, 2000);
    });

    // ── API Client ─────────────────────────────────────────────────────────────
    async function api(endpoint, options) {
        options = options || {};
        var headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers);

        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
        }

        var response = await fetch(API_BASE + endpoint, Object.assign({}, options, {
            headers: headers
        }));

        if (!response.ok) {
            var err;
            try { err = await response.json(); } catch (_) { err = { detail: 'An error occurred' }; }
            throw new Error(err.detail || 'Request failed');
        }

        // 204 No Content (e.g. DELETE) has an empty body — don't try to parse it
        if (response.status === 204) return null;

        var text = await response.text();
        if (!text) return null;
        return JSON.parse(text);
    }

    // ── Password Confirmation Validation ───────────────────────────────────────
    var regPassword = document.getElementById('registerPassword');
    var regConfirm  = document.getElementById('registerConfirmPassword');

    function checkPasswordMatch() {
        if (!regConfirm.value || !regPassword.value) {
            passwordMismatch.classList.remove('show');
            regConfirm.classList.remove('input-error');
            return;
        }
        if (regPassword.value !== regConfirm.value) {
            passwordMismatch.classList.add('show');
            regConfirm.classList.add('input-error');
        } else {
            passwordMismatch.classList.remove('show');
            regConfirm.classList.remove('input-error');
        }
    }

    if (regPassword) regPassword.addEventListener('input', checkPasswordMatch);
    if (regConfirm)  regConfirm.addEventListener('input', checkPasswordMatch);

    // ── Welcome View Handlers ──────────────────────────────────────────────────
    welcomeGuestBtn.addEventListener('click', function () {
        enterGuestMode();
    });

    welcomeLoginBtn.addEventListener('click', function () {
        showAuthView();
    });

    backToWelcome.addEventListener('click', function (e) {
        e.preventDefault();
        showWelcomeView();
    });

    // ── Auth Handlers ──────────────────────────────────────────────────────────
    loginForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        var login    = document.getElementById('loginEmail').value.trim();
        var password = document.getElementById('loginPassword').value;

        try {
            var data = await api('/auth/login', {
                method: 'POST',
                body: JSON.stringify({ login: login, password: password })
            });
            onAuthenticated(data);
        } catch (err) {
            showError(err.message);
        }
    });

    registerForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        var username = document.getElementById('registerUsername').value;
        var email    = document.getElementById('registerEmail').value;
        var password = document.getElementById('registerPassword').value;
        var confirm  = document.getElementById('registerConfirmPassword').value;

        // Frontend validation
        if (password !== confirm) {
            showError('Passwords do not match');
            return;
        }

        try {
            // Register
            await api('/auth/register', {
                method: 'POST',
                body: JSON.stringify({
                    username: username,
                    email: email,
                    password: password,
                    confirm_password: confirm
                })
            });
            // Auto-login
            var loginData = await api('/auth/login', {
                method: 'POST',
                body: JSON.stringify({ login: email, password: password })
            });
            onAuthenticated(loginData);
        } catch (err) {
            showError(err.message);
        }
    });

    function onAuthenticated(data) {
        token = data.access_token;
        localStorage.setItem('token', token);
        isGuest = false;
        currentUser = data.user || null;
        initializeApp();
    }

    function logout() {
        // Invalidate any in-flight session validation, then reset all session state
        appSessionVersion++;
        token = null;
        currentUser = null;
        isGuest = false;
        currentConversationId = null;
        guestConversations = [];
        activeConversations = [];
        localStorage.removeItem('token');
        showWelcomeView();
    }

    function confirmLogout() {
        logoutConfirm.hidden = false;
    }

    function closeLogoutConfirm() {
        logoutConfirm.hidden = true;
    }

    logoutBtn.addEventListener('click', confirmLogout);
    logoutConfirmYes.addEventListener('click', function () {
        closeLogoutConfirm();
        logout();
    });
    logoutConfirmNo.addEventListener('click', closeLogoutConfirm);
    logoutConfirmClose.addEventListener('click', closeLogoutConfirm);
    logoutConfirm.addEventListener('click', function (e) {
        if (e.target === logoutConfirm) closeLogoutConfirm();
    });

    // ── Google Sign-In ─────────────────────────────────────────────────────────
    var googleClientId = null;

    // Fetch public config on boot to learn whether Google Sign-In is enabled
    async function loadGoogleConfig() {
        try {
            var cfg = await api('/config');
            googleClientId = cfg.google_client_id || null;
            streamingEnabled = cfg.streaming_enabled || false;
            if (!googleClientId) return;
            loadGoogleScript();
        } catch (err) {
            console.error('Failed to load config:', err);
        }
    }

    // Dynamically load Google Identity Services if we have a client ID
    function loadGoogleScript() {
        if (typeof google !== 'undefined' && google.accounts) return;
        var script = document.createElement('script');
        script.src = 'https://accounts.google.com/gsi/client';
        script.async = true;
        script.defer = true;
        script.onload = initGoogle;
        script.onerror = function () {
            console.error('Failed to load Google Identity Services script.');
        };
        document.head.appendChild(script);
    }

    // Hidden container holds Google's real button so we can trigger it
    function ensureHiddenGoogleButton() {
        var container = document.getElementById('googleButtonHost');
        if (container) return container;
        container = document.createElement('div');
        container.id = 'googleButtonHost';
        container.style.display = 'none';
        document.body.appendChild(container);
        return container;
    }

    function initGoogle() {
        if (typeof google === 'undefined' || !google.accounts) return;

        google.accounts.id.initialize({
            client_id: googleClientId,
            callback: handleGoogleCredentialResponse
        });

        google.accounts.id.renderButton(
            ensureHiddenGoogleButton(),
            { theme: 'outline', size: 'large', type: 'standard' }
        );
    }

    googleLoginBtn.addEventListener('click', function () {
        if (!googleClientId) {
            showError(
                'Google Sign-In is not configured. ' +
                'Add GOOGLE_CLIENT_ID to .env, then restart the server.'
            );
            return;
        }
        if (typeof google === 'undefined' || !google.accounts) {
            showError('Google Sign-In is still loading. Please try again in a moment.');
            return;
        }

        var host = document.getElementById('googleButtonHost');
        var realButton = host && host.querySelector('div[role="button"]');
        if (realButton) {
            realButton.click();
        } else {
            google.accounts.id.prompt();
        }
    });

    async function handleGoogleCredentialResponse(response) {
        try {
            var data = await api('/auth/google', {
                method: 'POST',
                body: JSON.stringify({ id_token: response.credential })
            });
            onAuthenticated(data);
        } catch (err) {
            showError('Google sign-in failed: ' + err.message);
        }
    }

    // ── Guest Mode ─────────────────────────────────────────────────────────────
    function enterGuestMode() {
        // Every "Continue as Guest" starts a completely fresh session.
        // Invalidate any in-flight session validation and clear any lingering
        // auth state so guest requests are NOT authenticated as a real user
        // (and guest conversations are never saved to someone's account).
        appSessionVersion++;
        token = null;
        currentUser = null;
        currentConversationId = null;
        localStorage.removeItem('token');

        isGuest = true;
        guestConversations = [];
        activeConversations = [];
        updateAccountUI();
        showChatView();
        guestBanner.style.display = 'flex';
        var newChatLabel = newChatBtn.querySelector('.nav-label');
        if (newChatLabel) newChatLabel.textContent = '+ New Chat';
    }

    bannerSignupBtn.addEventListener('click', function () {
        showAuthView();
        // Switch to register tab
        document.querySelectorAll('.auth-tab').forEach(function (t) {
            t.classList.remove('active');
        });
        document.querySelectorAll('.auth-form').forEach(function (f) {
            f.classList.remove('active');
        });
        var regTab = document.querySelector('[data-tab="register"]');
        if (regTab) {
            regTab.classList.add('active');
            document.getElementById('registerForm').classList.add('active');
        }
    });

    bannerDismissBtn.addEventListener('click', function () {
        guestBanner.style.display = 'none';
    });

    // ── Empty State (greeting) ────────────────────────────────────────────────
    function showEmptyState() {
        messagesContainer.innerHTML =
            '<div class="empty-state" id="emptyState">' +
                '<img src="assets/julibot-logo-v2.png?v=2" height="110" alt="JULIBOT" class="logo" onerror="this.style.display=\'none\'">' +
                '<h2>Welcome to JULIBOT</h2>' +
                '<p class="tagline">How may I help you today?</p>' +
            '</div>';
        emptyState = document.getElementById('emptyState');
        syncChatMode();
    }

    // ── New Conversation ───────────────────────────────────────────────────────
    newChatBtn.addEventListener('click', function () {
        currentConversationId = null;
        showEmptyState();
        conversationsList.querySelectorAll('.conversation-item').forEach(function (item) {
            item.classList.remove('active');
        });
        messageInput.focus();
        if (isMobileView()) closeSidebarDrawer();
    });

    // ── Last message tracking (for retry) ─────────────────────────────────
    var lastSentMessage = '';

    // Expose retry function globally so error buttons can call it
    window._retryLastMessage = function () {
        if (!lastSentMessage || isStreaming) return;
        messageInput.value = lastSentMessage;
        sendMessage();
    };

    // ── Send Message ───────────────────────────────────────────────────────────
    async function sendMessage() {
        var message = messageInput.value.trim();
        if (!message || isStreaming) return;
        lastSentMessage = message;

        sendBtn.disabled = true;
        messageInput.value = '';
        resetTextarea();
        updateSendButton();

        addMessage('user', message);
        emptyState.style.display = 'none';
        syncChatMode();

        // Create polished thinking/loading placeholder for assistant response
        var assistantDiv = document.createElement('div');
        assistantDiv.className = 'message assistant streaming';
        assistantDiv.innerHTML =
            '<div class="message-avatar">J</div>' +
            '<div class="message-body">' +
                '<div class="message-role">JULIBOT</div>' +
                '<div class="message-content">' +
                    '<div class="message-text">' +
                        '<div class="thinking-indicator">' +
                            '<div class="thinking-dots">' +
                                '<div class="thinking-dot"></div>' +
                                '<div class="thinking-dot"></div>' +
                                '<div class="thinking-dot"></div>' +
                            '</div>' +
                            '<div class="thinking-label">Preparing a response…</div>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';
        messagesContainer.appendChild(assistantDiv);
        scrollToBottom();

        try {
            if (streamingEnabled) {
                await sendStreamingMessage(message, assistantDiv);
            } else {
                await sendNonStreamingMessage(message, assistantDiv);
            }
        } catch (err) {
            assistantDiv.classList.remove('streaming');
            var textDiv = assistantDiv.querySelector('.message-text');
            textDiv.innerHTML =
                '<div class="message-error">' +
                    '<span class="message-error-icon">⚠</span>' +
                    '<div>' +
                        '<div class="message-error-text">' + escapeHtml(err.message) + '</div>' +
                        '<button class="message-error-retry" onclick="window._retryLastMessage()">Try again</button>' +
                    '</div>' +
                '</div>';
        } finally {
            sendBtn.disabled = false;
            messageInput.focus();
        }
    }

    async function sendStreamingMessage(message, assistantDiv) {
        isStreaming = true;
        var fullContent = '';
        var textDiv = assistantDiv.querySelector('.message-text');
        var messageId = generateId();

        // For guests
        if (isGuest) {
            if (!currentConversationId) {
                currentConversationId = 'g_' + generateId();
                guestConversations.push({
                    id: currentConversationId,
                    title: message.substring(0, 30) + (message.length > 30 ? '…' : ''),
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                    messages: []
                });
            }

            var guestConvObj = guestConversations.find(function (c) {
                return c.id === currentConversationId;
            });
            if (guestConvObj) {
                guestConvObj.messages.push({
                    id: generateId(),
                    role: 'user',
                    content: message,
                    created_at: new Date().toISOString()
                });
            }
        }

        // Thinking indicator stays visible until first content arrives

        // Stream via POST + fetch, parsing SSE from the response body.
        // EventSource only supports GET, but the backend stream endpoint is POST
        // (and needs the Authorization header for registered users).
        var headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = 'Bearer ' + token;

        var fetchAbort = new AbortController();
        abortController = { abort: function() { fetchAbort.abort(); } };

        try {
            var response = await fetch(API_BASE + '/conversations/chat/stream', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    message: message,
                    conversation_id: isGuest ? null : (currentConversationId || null)
                }),
                signal: fetchAbort.signal
            });

            if (!response.ok) {
                throw new Error('Server returned ' + response.status);
            }

            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';

            // Handles one parsed SSE data event. Returns true when done/error received.
            function handleSseData(data) {
                if (data.type === 'content') {
                    fullContent += data.content;
                    textDiv.innerHTML = renderContent(fullContent);
                    scrollToBottom();
                } else if (data.type === 'done') {
                    assistantDiv.classList.remove('streaming');
                    assistantDiv.dataset.id = data.message ? data.message.id || messageId : messageId;

                    if (isGuest) {
                        var conv = guestConversations.find(function (c) {
                            return c.id === currentConversationId;
                        });
                        if (conv) {
                            conv.messages.push({
                                id: messageId,
                                role: 'assistant',
                                content: fullContent,
                                created_at: new Date().toISOString()
                            });
                            conv.updated_at = new Date().toISOString();
                        }
                        renderConversations();
                    } else {
                        currentConversationId = data.conversation_id;
                        loadConversations();
                    }
                    return true;
                } else if (data.type === 'error') {
                    textDiv.innerHTML =
                        '<div class="message-error">' +
                            '<span class="message-error-icon">⚠</span>' +
                            '<div class="message-error-text">' + escapeHtml(data.error) + '</div>' +
                        '</div>';
                    return true;
                }
                return false;
            }

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;

                buffer += decoder.decode(chunk.value, { stream: true });

                var parts = buffer.split('\n\n');
                buffer = parts.pop(); // trailing partial event stays in buffer

                for (var i = 0; i < parts.length; i++) {
                    var lines = parts[i].split('\n');
                    var dataLine = '';
                    for (var j = 0; j < lines.length; j++) {
                        if (lines[j].indexOf('data:') === 0) {
                            dataLine += lines[j].substring(5).trim();
                        }
                    }
                    if (!dataLine) continue;

                    var data;
                    try {
                        data = JSON.parse(dataLine);
                    } catch (e) {
                        console.error('Error parsing SSE event:', e);
                        continue;
                    }

                    if (handleSseData(data)) {
                        reader.cancel();
                        isStreaming = false;
                        abortController = null;
                        return;
                    }
                }
            }

            // Stream closed without an explicit done/error event
            if (fullContent) {
                textDiv.innerHTML = renderContent(fullContent);
            }
            assistantDiv.classList.remove('streaming');
            isStreaming = false;
            abortController = null;
        } catch (err) {
            console.error('SSE error:', err);
            if (err && err.name === 'AbortError') {
                // User cancelled — leave the placeholder as-is
            } else if (textDiv.innerHTML === '') {
                textDiv.innerHTML =
                    '<div class="message-error">' +
                        '<span class="message-error-icon">⚠</span>' +
                        '<div class="message-error-text">Connection error. Please try again.</div>' +
                    '</div>';
            }
            assistantDiv.classList.remove('streaming');
            isStreaming = false;
            abortController = null;
        }
    }

    async function sendNonStreamingMessage(message, assistantDiv) {
        var textDiv = assistantDiv.querySelector('.message-text');

        // Thinking indicator stays visible until content arrives

        // ── Guest: keep conversation in-memory, call API for response ──
        if (isGuest) {
            if (!currentConversationId) {
                currentConversationId = 'g_' + generateId();
                guestConversations.push({
                    id: currentConversationId,
                    title: message.substring(0, 30) + (message.length > 30 ? '…' : ''),
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                    messages: []
                });
            }

            var guestConvObj = guestConversations.find(function (c) {
                return c.id === currentConversationId;
            });
            if (guestConvObj) {
                guestConvObj.messages.push({
                    id: generateId(),
                    role: 'user',
                    content: message,
                    created_at: new Date().toISOString()
                });
            }

            // Guest requests send no conversation_id (guests are session-only)
            var data = await api('/conversations/chat', {
                method: 'POST',
                body: JSON.stringify({ message: message })
            });

            var assistantMsg = {
                id: data.message ? data.message.id || generateId() : generateId(),
                role: 'assistant',
                content: data.message ? data.message.content : 'No response',
                created_at: new Date().toISOString()
            };
            if (guestConvObj) {
                guestConvObj.messages.push(assistantMsg);
                guestConvObj.updated_at = new Date().toISOString();
                guestConvObj.title = guestConvObj.messages[0].content.substring(0, 30) +
                    (guestConvObj.messages[0].content.length > 30 ? '…' : '');
            }

            renderConversations();
            assistantDiv.classList.remove('streaming');
            textDiv.innerHTML = renderContent(assistantMsg.content);
            assistantDiv.dataset.id = assistantMsg.id;

        } else {
            // ── Registered user: server-side persistence ──
            var data = await api('/conversations/chat', {
                method: 'POST',
                body: JSON.stringify({
                    message: message,
                    conversation_id: currentConversationId
                })
            });

            if (!currentConversationId) {
                currentConversationId = data.conversation_id;
                await loadConversations();
            }

            assistantDiv.classList.remove('streaming');
            textDiv.innerHTML = renderContent(data.message.content);
            assistantDiv.dataset.id = data.message.id;
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ── Messages ───────────────────────────────────────────────────────────────
    function addMessage(role, content, id) {
        var div = document.createElement('div');
        div.className = 'message ' + role;
        div.dataset.id = id || '';
        var avatarLabel = role === 'user'
            ? (isGuest ? 'G' : getInitial(currentUser))
            : 'J';
        div.innerHTML =
            '<div class="message-avatar">' + avatarLabel + '</div>' +
            '<div class="message-body">' +
                '<div class="message-role">' + (role === 'user' ? 'You' : 'JULIBOT') + '</div>' +
                '<div class="message-content">' +
                    '<div class="message-text">' + renderContent(content) + '</div>' +
                '</div>' +
            '</div>';
        messagesContainer.appendChild(div);
        scrollToBottom();
    }

    function getInitial(user) {
        if (!user) return 'U';
        // Prefer display name, then username, then email
        var name = user.display_name || user.username || user.email;
        if (!name) return 'U';
        return name.charAt(0).toUpperCase();
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // ── Conversations ──────────────────────────────────────────────────────────
    async function loadConversations() {
        if (isGuest) {
            activeConversations = guestConversations;
            renderConversations();
            return;
        }
        try {
            activeConversations = await api('/conversations');
            renderConversations();
        } catch (err) {
            console.error('Failed to load conversations:', err);
        }
    }

    function renderConversations() {
        conversationsList.innerHTML = activeConversations.map(function (conv) {
            var isActive = conv.id === currentConversationId ? ' active' : '';
            var dateStr = new Date(conv.updated_at).toLocaleDateString();
            var actions = isGuest ? '' :
                '<div class="conv-actions">' +
                    '<button class="conv-action" data-action="rename" data-id="' + conv.id + '" title="Rename">✎</button>' +
                    '<button class="conv-action" data-action="delete" data-id="' + conv.id + '" title="Delete">🗑</button>' +
                '</div>';
            return (
                '<div class="conversation-item' + isActive + '" data-id="' + conv.id + '">' +
                    '<div class="conv-main">' +
                        '<div class="title">' + escapeHtml(conv.title) + '</div>' +
                        '<div class="date">' + dateStr + '</div>' +
                    '</div>' +
                    actions +
                '</div>'
            );
        }).join('');

        conversationsList.querySelectorAll('.conversation-item').forEach(function (item) {
            item.addEventListener('click', function (e) {
                // Ignore clicks on action buttons
                if (e.target.closest('.conv-action')) return;
                loadConversation(item.dataset.id);
            });
        });

        conversationsList.querySelectorAll('.conv-action[data-action="rename"]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                renameConversation(btn.dataset.id);
            });
        });

        conversationsList.querySelectorAll('.conv-action[data-action="delete"]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                deleteConversation(btn.dataset.id);
            });
        });
    }

    var pendingRenameId = null;

    function renameConversation(id) {
        var conv = activeConversations.find(function (c) { return String(c.id) === String(id); });
        if (!conv) return;
        pendingRenameId = id;
        renameInput.value = conv.title || '';
        renameError.textContent = '';
        renameError.classList.remove('show');
        renameModal.hidden = false;
        renameInput.focus();
        renameInput.select();
    }

    function closeRenameModal() {
        renameModal.hidden = true;
        pendingRenameId = null;
    }

    renameConfirmBtn.addEventListener('click', async function () {
        var id = pendingRenameId;
        var newTitle = renameInput.value.trim();
        if (!newTitle) {
            renameError.textContent = 'Please enter a title.';
            renameError.classList.add('show');
            renameInput.focus();
            return;
        }
        closeRenameModal();
        try {
            await api('/conversations/' + id, {
                method: 'PATCH',
                body: JSON.stringify({ title: newTitle })
            });
            var conv = activeConversations.find(function (c) { return String(c.id) === String(id); });
            if (conv) conv.title = newTitle;
            renderConversations();
        } catch (err) {
            alert('Rename failed: ' + err.message);
        }
    });

    renameCancelBtn.addEventListener('click', closeRenameModal);
    renameCloseBtn.addEventListener('click', closeRenameModal);
    renameModal.addEventListener('click', function (e) {
        if (e.target === renameModal) closeRenameModal();
    });
    renameInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') renameConfirmBtn.click();
    });

    var pendingDeleteId = null;

    function openDeleteConfirm(id) {
        pendingDeleteId = id;
        deleteConfirm.hidden = false;
    }

    function closeDeleteConfirm() {
        deleteConfirm.hidden = true;
        pendingDeleteId = null;
    }

    function deleteConversation(id) {
        openDeleteConfirm(id);
    }

    deleteConfirmYes.addEventListener('click', async function () {
        var id = pendingDeleteId;
        closeDeleteConfirm();
        if (id == null) return;
        try {
            await api('/conversations/' + id, { method: 'DELETE' });
            activeConversations = activeConversations.filter(function (c) {
                return String(c.id) !== String(id);
            });
            if (String(currentConversationId) === String(id)) {
                currentConversationId = null;
                resetChatArea();
            }
            renderConversations();
        } catch (err) {
            alert('Delete failed: ' + err.message);
        }
    });

    deleteConfirmCancel.addEventListener('click', closeDeleteConfirm);
    deleteConfirmClose.addEventListener('click', closeDeleteConfirm);
    deleteConfirm.addEventListener('click', function (e) {
        if (e.target === deleteConfirm) closeDeleteConfirm();
    });

    async function loadConversation(id) {
        if (isGuest) {
            var guestConv = guestConversations.find(function (c) { return String(c.id) === String(id); });
            if (!guestConv) return;
            currentConversationId = guestConv.id;
            if (guestConv.messages.length) {
                messagesContainer.innerHTML = '';
            } else {
                showEmptyState();
            }
            guestConv.messages.forEach(function (msg) {
                addMessage(msg.role, msg.content, msg.id);
            });
            conversationsList.querySelectorAll('.conversation-item').forEach(function (item) {
                item.classList.toggle('active', String(item.dataset.id) === String(id));
            });
            if (isMobileView()) closeSidebarDrawer();
            syncChatMode();
            return;
        }

        try {
            var conv = await api('/conversations/' + id);
            currentConversationId = conv.id;
            if (conv.messages.length) {
                messagesContainer.innerHTML = '';
            } else {
                showEmptyState();
            }
            conv.messages.forEach(function (msg) {
                addMessage(msg.role, msg.content, msg.id);
            });
            conversationsList.querySelectorAll('.conversation-item').forEach(function (item) {
                item.classList.toggle('active', parseInt(item.dataset.id, 10) === conv.id);
            });
            if (isMobileView()) closeSidebarDrawer();
            syncChatMode();
        } catch (err) {
            console.error('Failed to load conversation:', err);
        }
    }

    // ── View Switching ─────────────────────────────────────────────────────────
    function showWelcomeView() {
        welcomeContainer.style.display = 'flex';
        authContainer.style.display = 'none';
        chatContainer.classList.remove('active');
        guestBanner.style.display = 'none';
        closeAccountPopup();
        closeProfileModal();
    }

    function showAuthView() {
        welcomeContainer.style.display = 'none';
        authContainer.style.display = 'flex';
        chatContainer.classList.remove('active');
        guestBanner.style.display = 'none';
    }

    function showChatView() {
        welcomeContainer.style.display = 'none';
        authContainer.style.display = 'none';
        chatContainer.classList.add('active');
        if (!isGuest) guestBanner.style.display = 'none';

        resetChatArea();
    }

    function resetChatArea() {
        currentConversationId = null;
        showEmptyState();
        activeConversations = [];
        renderConversations();
    }

    // ── Account avatar + popup menu ──────────────────────────────────────────
    var PROFILE_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    var LOGOUT_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>';
    var LOGIN_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>';

    function setAvatarInitial(text) {
        var initial = userAvatar.querySelector('.avatar-initial');
        if (initial) initial.textContent = text;
    }

    function renderAvatarImage(photoUrl) {
        var img = userAvatar.querySelector('.avatar-img');
        var initial = userAvatar.querySelector('.avatar-initial');
        if (photoUrl) {
            img.src = photoUrl;
            img.hidden = false;
            initial.hidden = true;
        } else {
            img.removeAttribute('src');
            img.hidden = true;
            initial.hidden = false;
        }
    }

    // Render the sidebar footer (avatar, name, guest vs logged-in) from state
    function updateAccountUI() {
        if (isGuest) {
            userInfo.classList.add('guest');
            userEmail.textContent = 'Guest';
            userSub.textContent = '';
            userAvatar.dataset.tooltip = 'Guest';
            renderAvatarImage(null);
            setAvatarInitial('G');
            userAvatar.setAttribute('aria-label', 'Account menu — Guest');
        } else if (currentUser) {
            userInfo.classList.remove('guest');
            var name = currentUser.display_name || currentUser.username || currentUser.email;
            var email = currentUser.email || '';
            userEmail.textContent = name;
            userSub.textContent = email || 'Account / Profile';
            userAvatar.dataset.tooltip = email || name;
            renderAvatarImage(currentUser.profile_photo_url);
            setAvatarInitial(getInitial(currentUser));
            userAvatar.setAttribute('aria-label', 'Account menu — ' + name);
        }
        buildAccountPopup();
        updateAvatarInteractivity();
    }

    function accountPopupItem(action, label, iconSvg, extraClass) {
        return '<button class="account-popup-item' + (extraClass ? ' ' + extraClass : '') +
            '" data-action="' + action + '" role="menuitem" type="button">' +
            '<span class="popup-icon">' + iconSvg + '</span>' +
            '<span>' + label + '</span>' +
        '</button>';
    }

    function buildAccountPopup() {
        var items;
        if (isGuest) {
            items = accountPopupItem('login', 'Login', LOGIN_ICON);
        } else {
            // The sidebar footer already shows a Logout button when expanded
            // (and in the mobile drawer), so only offer Logout in the popup
            // when the sidebar is collapsed on desktop.
            var showLogout = sidebar.classList.contains('collapsed') && !isMobileView();
            items = accountPopupItem('profile', 'Profile', PROFILE_ICON) +
                    (showLogout ? accountPopupItem('logout', 'Logout', LOGOUT_ICON, 'danger') : '');
        }
        accountPopup.innerHTML = items;
    }

    // Position the popup just above the avatar, floating over the chat area
    // (outside the sidebar) and clamped to the viewport. `position: fixed`
    // keeps it out of the sidebar's overflow clipping entirely.
    function positionAccountPopup() {
        var rect = userAvatar.getBoundingClientRect();
        var popupWidth = accountPopup.offsetWidth;
        var popupHeight = accountPopup.offsetHeight;
        var gap = 8;
        var margin = 8;

        // Horizontal: align to the avatar's left edge, clamped to the viewport
        var left = rect.left;
        if (left + popupWidth > window.innerWidth - margin) {
            left = window.innerWidth - popupWidth - margin;
        }
        if (left < margin) left = margin;
        accountPopup.style.left = left + 'px';

        // Vertical: prefer above the avatar; flip below if there's no room
        if (rect.top < popupHeight + gap * 2) {
            accountPopup.style.top = (rect.bottom + gap) + 'px';
            accountPopup.style.bottom = 'auto';
        } else {
            accountPopup.style.bottom = (window.innerHeight - rect.top + gap) + 'px';
            accountPopup.style.top = 'auto';
        }
    }

    function openAccountPopup() {
        positionAccountPopup();
        accountPopup.classList.add('open');
        userInfo.classList.add('account-open');
        userAvatar.setAttribute('aria-expanded', 'true');
    }

    function closeAccountPopup() {
        accountPopup.classList.remove('open');
        userInfo.classList.remove('account-open');
        userAvatar.setAttribute('aria-expanded', 'false');
    }

    // In guest mode the footer already shows a Login button when the sidebar is
    // expanded (and in the mobile drawer), so the avatar popup is redundant
    // there. Only the collapsed sidebar (button hidden) needs it.
    function shouldShowAccountPopup() {
        if (isGuest && (isMobileView() || !sidebar.classList.contains('collapsed'))) {
            return false;
        }
        return true;
    }

    // Mirrors shouldShowAccountPopup() into a class so the avatar can drop its
    // clickable affordance (cursor / hover ring) when the popup is suppressed.
    // Also rebuilds the popup so Profile/Logout reflect the current sidebar state.
    function updateAvatarInteractivity() {
        userInfo.classList.toggle('popup-enabled', shouldShowAccountPopup());
        if (!isGuest) buildAccountPopup();
    }

    function toggleAccountPopup() {
        if (!shouldShowAccountPopup()) return;
        if (accountPopup.classList.contains('open')) {
            closeAccountPopup();
        } else {
            openAccountPopup();
        }
    }

    userAvatar.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleAccountPopup();
    });

    userAvatar.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggleAccountPopup();
        }
    });

    // Close the popup when clicking anywhere outside the avatar or the popup
    document.addEventListener('click', function (e) {
        if (accountPopup.classList.contains('open') &&
            !e.target.closest('.user-info') &&
            !e.target.closest('.account-popup')) {
            closeAccountPopup();
        }
    });

    // Keep the popup anchored to the avatar while the viewport changes
    window.addEventListener('resize', function () {
        updateAvatarInteractivity();
        if (accountPopup.classList.contains('open')) positionAccountPopup();
    });

    window.addEventListener('scroll', function () {
        if (accountPopup.classList.contains('open')) positionAccountPopup();
    });

    accountPopup.addEventListener('click', function (e) {
        var item = e.target.closest('.account-popup-item');
        if (!item) return;
        var action = item.dataset.action;
        closeAccountPopup();
        if (action === 'profile') {
            openProfileModal();
        } else if (action === 'logout') {
            confirmLogout();
        } else if (action === 'login') {
            showAuthView();
            showLoginTab();
        }
    });

    function showLoginTab() {
        document.querySelectorAll('.auth-tab').forEach(function (t) {
            t.classList.remove('active');
        });
        document.querySelectorAll('.auth-form').forEach(function (f) {
            f.classList.remove('active');
        });
        var loginTab = document.querySelector('[data-tab="login"]');
        if (loginTab) {
            loginTab.classList.add('active');
            var form = document.getElementById('loginForm');
            if (form) form.classList.add('active');
        }
    }

    if (guestLoginBtn) {
        guestLoginBtn.addEventListener('click', function () {
            showAuthView();
            showLoginTab();
        });
    }

    // ── Profile modal (edit display name + photo) ─────────────────────────────
    var pendingPhoto; // undefined = no change, null = remove, string = new data URL

    function showProfileError(message) {
        profileError.textContent = message;
        profileError.classList.add('show');
    }

    function hideProfileError() {
        profileError.textContent = '';
        profileError.classList.remove('show');
    }

    function renderProfilePhotoPreview() {
        var img = profilePhotoPreview.querySelector('img');
        var initial = profilePhotoPreview.querySelector('.profile-photo-initial');
        var photo = (pendingPhoto !== undefined) ? pendingPhoto : (currentUser ? currentUser.profile_photo_url : null);
        if (photo) {
            img.src = photo;
            img.hidden = false;
            initial.hidden = true;
            profilePhotoRemoveBtn.hidden = false;
        } else {
            img.removeAttribute('src');
            img.hidden = true;
            initial.hidden = false;
            initial.textContent = getInitial(currentUser);
            profilePhotoRemoveBtn.hidden = true;
        }
    }

    function openProfileModal() {
        if (isGuest || !currentUser) return;
        pendingPhoto = undefined;
        profileDisplayName.value = currentUser.display_name || currentUser.username || '';
        hideProfileError();
        renderProfilePhotoPreview();
        profileModal.hidden = false;
        profileDisplayName.focus();
    }

    function closeProfileModal() {
        pendingPhoto = undefined;
        profileModal.hidden = true;
    }

    async function saveProfile() {
        var payload = {};
        var displayName = profileDisplayName.value.trim();
        payload.display_name = displayName || null;
        if (pendingPhoto !== undefined) {
            payload.profile_photo_url = pendingPhoto;
        }

        profileSaveBtn.disabled = true;
        hideProfileError();
        try {
            currentUser = await api('/auth/me', {
                method: 'PATCH',
                body: JSON.stringify(payload)
            });
            updateAccountUI();
            closeProfileModal();
            showToast('Profile updated');
        } catch (err) {
            showProfileError(err.message);
        } finally {
            profileSaveBtn.disabled = false;
        }
    }

    // Downscale the chosen image to ≤256px before uploading (keeps the stored
    // data URL small and within the backend's size limit)
    function handlePhotoFile(file) {
        if (!file || !file.type || file.type.indexOf('image/') !== 0) {
            showProfileError('Please choose an image file.');
            return;
        }
        var reader = new FileReader();
        reader.onload = function (ev) {
            var img = new Image();
            img.onload = function () {
                var MAX = 256;
                var scale = Math.min(1, MAX / Math.max(img.width, img.height));
                var canvas = document.createElement('canvas');
                canvas.width = Math.max(1, Math.round(img.width * scale));
                canvas.height = Math.max(1, Math.round(img.height * scale));
                canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                var dataUrl;
                try {
                    dataUrl = canvas.toDataURL('image/jpeg', 0.85);
                } catch (err) {
                    dataUrl = ev.target.result; // fall back to the original
                }
                pendingPhoto = dataUrl;
                renderProfilePhotoPreview();
                hideProfileError();
            };
            img.onerror = function () {
                showProfileError('Could not read that image.');
            };
            img.src = ev.target.result;
        };
        reader.readAsDataURL(file);
    }

    profilePhotoBtn.addEventListener('click', function () {
        profilePhotoInput.click();
    });

    profilePhotoInput.addEventListener('change', function () {
        var file = profilePhotoInput.files && profilePhotoInput.files[0];
        if (file) handlePhotoFile(file);
        profilePhotoInput.value = '';
    });

    profilePhotoRemoveBtn.addEventListener('click', function () {
        pendingPhoto = null;
        renderProfilePhotoPreview();
        hideProfileError();
    });

    profileSaveBtn.addEventListener('click', saveProfile);
    profileCancelBtn.addEventListener('click', closeProfileModal);
    profileCloseBtn.addEventListener('click', closeProfileModal);

    // Clicking the overlay backdrop closes the modal
    profileModal.addEventListener('click', function (e) {
        if (e.target === profileModal) closeProfileModal();
    });

    // ── Init ───────────────────────────────────────────────────────────────────
    async function initializeApp() {
        if (isGuest) return; // Guest mode has no server-side user

        var myVersion = ++appSessionVersion;

        // Hide auth views immediately so a stale landing page can't flash
        // (or be clicked) while we re-validate the stored token.
        welcomeContainer.style.display = 'none';
        authContainer.style.display = 'none';

        try {
            currentUser = await api('/auth/me');
            if (myVersion !== appSessionVersion) return; // superseded

            isGuest = currentUser.user_type === 'guest';
            updateAccountUI();
            showChatView();
            await loadConversations();
        } catch (err) {
            if (myVersion !== appSessionVersion) return; // superseded
            console.warn('Session validation failed:', err);
            token = null;
            currentUser = null;
            isGuest = false;
            localStorage.removeItem('token');
            showWelcomeView();
        }
    }

    // ── Textarea Auto-Resize ───────────────────────────────────────────────────
    function resetTextarea() {
        messageInput.style.height = 'auto';
    }

    // Show/hide the send arrow based on whether the input has content
    function updateSendButton() {
        if (chatInputBox) chatInputBox.classList.toggle('has-text', messageInput.value.trim().length > 0);
    }

    // Toggle the centered "welcome" layout based on the empty-state visibility
    function syncChatMode() {
        if (!mainChat) return;
        var empty = document.querySelector('#emptyState');
        var welcome = !!empty && empty.offsetParent !== null;
        mainChat.classList.toggle('welcome', welcome);
    }

    messageInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 160) + 'px';
        updateSendButton();
    });
    updateSendButton();
    syncChatMode();

    // ── Server Connection Check ──────────────────────────────────────────────
    // Detects two common reasons "localhost refuses to connect":
    //   1. User opened src/index.html directly via file:// (no server at all)
    //   2. User navigated to localhost:port but the server isn't running
    // Shows a clear overlay with instructions instead of silent failure.

    function showConnectionError(message) {
        var overlay = document.createElement('div');
        overlay.id = 'serverErrorOverlay';
        overlay.style.cssText =
            'position:fixed;inset:0;background:rgba(15,17,21,.96);z-index:9999;' +
            'display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML =
            '<div style="max-width:540px;padding:32px;text-align:center;' +
                'color:#fff;font-family:-apple-system,system-ui,sans-serif;">' +
                '<div style="font-size:48px;margin-bottom:12px;">⚠️</div>' +
                '<h2 style="font-size:22px;margin:0 0 12px;">' +
                    'Can\'t reach the JULIBOT server' +
                '</h2>' +
                '<p style="color:#aab;line-height:1.6;margin:0 0 16px;">' +
                    escapeHtml(message) +
                '</p>' +
                '<p style="color:#889;font-size:13px;margin:0 0 8px;">' +
                    'From the project folder, run:' +
                '</p>' +
                '<pre style="background:#1c1e26;padding:12px 16px;border-radius:8px;' +
                    'text-align:left;color:#7ee;font-size:13px;overflow-x:auto;' +
                    'margin:0 0 16px;">' +
                    'python run.py\n' +
                    '# then open  http://localhost:8000' +
                '</pre>' +
                '<button onclick="location.reload()" style="' +
                    'padding:10px 24px;background:#4f7cff;color:#fff;border:none;' +
                    'border-radius:8px;font-size:14px;cursor:pointer;' +
                    'transition:background .15s;">' +
                    'Retry' +
                '</button>' +
            '</div>';
        document.body.appendChild(overlay);
    }

    async function checkServerConnection() {
        if (window.location.protocol === 'file:') {
            showConnectionError(
                'You opened this file directly from disk instead of through the server. ' +
                'JULIBOT\'s backend must be running to serve the chat.'
            );
            return;
        }
        try {
            await api('/health');
        } catch (err) {
            showConnectionError(
                'The backend server is not responding on this address. ' +
                'It may have stopped or crashed — start it again and reload this page.'
            );
        }
    }

    // ── Boot ───────────────────────────────────────────────────────────────────
    loadGoogleConfig();  // Non-blocking: loads Google button config
    checkStreamingConfig();  // Check if streaming is enabled
    checkServerConnection();  // Detect unreachable-server state

    if (token) {
        initializeApp();
    } else {
        showWelcomeView();
    }

})();
