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

        // Convert code blocks
        escaped = escaped.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
            return '<pre class="code-block"><code class="language-' + lang + '">' + code.trim() + '</code></pre>';
        });

        // Convert inline code
        escaped = escaped.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

        // Convert bold
        escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Convert italic
        escaped = escaped.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Convert newlines to <br>
        escaped = escaped.replace(/\n/g, '<br>');

        return escaped;
    }

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

    logoutBtn.addEventListener('click', function () {
        // Reset all session state
        token = null;
        currentUser = null;
        isGuest = false;
        currentConversationId = null;
        guestConversations = [];
        activeConversations = [];
        localStorage.removeItem('token');
        showWelcomeView();
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
        // Every "Continue as Guest" starts a fresh session
        isGuest = true;
        guestConversations = [];
        showChatView();
        guestBanner.style.display = 'flex';
        userEmail.textContent = 'Guest';
        userAvatar.textContent = 'G';
        newChatBtn.textContent = '+ New Chat';
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
                '<img src="assets/julibot-logo.png" height="110" alt="JULIBOT" class="logo">' +
                '<h2>Welcome to JULIBOT</h2>' +
                '<p class="tagline">How may I help you today?</p>' +
            '</div>';
        emptyState = document.getElementById('emptyState');
    }

    // ── New Conversation ───────────────────────────────────────────────────────
    newChatBtn.addEventListener('click', function () {
        currentConversationId = null;
        showEmptyState();
        conversationsList.querySelectorAll('.conversation-item').forEach(function (item) {
            item.classList.remove('active');
        });
        messageInput.focus();
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

        addMessage('user', message);
        emptyState.style.display = 'none';

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
        if (!user || !user.email) return 'U';
        // Avatar is the initial of the email, e.g. montillano@ → "M"
        return user.email.charAt(0).toUpperCase();
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

    async function renameConversation(id) {
        var conv = activeConversations.find(function (c) { return String(c.id) === String(id); });
        if (!conv) return;
        var newTitle = prompt('Rename conversation:', conv.title);
        if (!newTitle || !newTitle.trim()) return;
        newTitle = newTitle.trim();

        try {
            await api('/conversations/' + id, {
                method: 'PATCH',
                body: JSON.stringify({ title: newTitle })
            });
            conv.title = newTitle;
            renderConversations();
        } catch (err) {
            alert('Rename failed: ' + err.message);
        }
    }

    async function deleteConversation(id) {
        if (!confirm('Delete this conversation? This cannot be undone.')) return;

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
    }

    async function loadConversation(id) {
        if (isGuest) {
            var guestConv = guestConversations.find(function (c) { return String(c.id) === String(id); });
            if (!guestConv) return;
            currentConversationId = guestConv.id;
            chatTitle.textContent = guestConv.title;
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
            return;
        }

        try {
            var conv = await api('/conversations/' + id);
            currentConversationId = conv.id;
            chatTitle.textContent = conv.title;
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
        chatTitle.textContent = isGuest ? 'New Chat' : 'Select a conversation';
        showEmptyState();
        activeConversations = [];
        renderConversations();
    }

    // ── Init ───────────────────────────────────────────────────────────────────
    async function initializeApp() {
        if (isGuest) return; // Guest mode has no server-side user

        try {
            currentUser = await api('/auth/me');
            isGuest = currentUser.user_type === 'guest';
            userEmail.textContent = currentUser.email;
            userAvatar.textContent = getInitial(currentUser);
            showChatView();
            await loadConversations();
        } catch (err) {
            localStorage.removeItem('token');
            token = null;
            isGuest = false;
            showWelcomeView();
        }
    }

    // ── Textarea Auto-Resize ───────────────────────────────────────────────────
    function resetTextarea() {
        messageInput.style.height = 'auto';
    }

    messageInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 160) + 'px';
    });

    // ── Boot ───────────────────────────────────────────────────────────────────
    loadGoogleConfig();  // Non-blocking: loads Google button config
    checkStreamingConfig();  // Check if streaming is enabled

    if (token) {
        initializeApp();
    } else {
        showWelcomeView();
    }

})();
