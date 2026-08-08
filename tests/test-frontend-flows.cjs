'use strict';
/* Integration test for src/js/app.js auth/guest flows.
 * Runs app.js in jsdom with a mocked backend and verifies:
 *  1. Login/register lands on the chat view (no ReferenceError, no bounce back).
 *  2. Logout returns to welcome and clears the token.
 *  3. Guest mode starts fresh: token cleared, guest banner shown, no auth leak.
 */
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = 'C:\\Users\\JULS\\myprojects\\aichat';
const html = fs.readFileSync(path.join(root, 'src', 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'src', 'js', 'app.js'), 'utf8');

const dom = new JSDOM(html, { url: 'http://127.0.0.1:8000/', runScripts: 'outside-only' });
const { window } = dom;
const { document } = window;

window.localStorage.clear();
window.AbortController = class { constructor() { this.signal = {}; } abort() {} };
window.confirm = () => true;
window.prompt = () => null;
window.alert = () => {};

// ---- request tracker (for verifying guest auth behavior) ----
let lastReq = null;

// ---- mocked backend ----
const backend = { users: new Map() };
function issueToken(userId) { return 'tok-' + userId; }
async function handle(apiPath, opts) {
  const method = (opts && opts.method) || 'GET';
  let body = {};
  try { body = opts && opts.body ? JSON.parse(opts.body) : {}; } catch (e) { /* ignore */ }
  const auth = (opts && opts.headers && opts.headers.Authorization) || '';

  if (apiPath === '/api/auth/login' && method === 'POST') {
    const u = [...backend.users.values()].find(
      (x) => (x.email === body.login || x.username === body.login) && x.password === body.password
    );
    if (!u) return { ok: false, status: 401, json: () => Promise.resolve({ detail: 'Incorrect email, username, or password' }) };
    return { ok: true, status: 200, json: () => Promise.resolve({ access_token: issueToken(u.id), token_type: 'bearer', user: { email: u.email, username: u.username, id: u.id, user_type: 'registered' } }) };
  }
  if (apiPath === '/api/auth/register' && method === 'POST') {
    const id = backend.users.size + 1;
    const u = { id, email: body.email, username: body.username, password: body.password };
    backend.users.set(id, u);
    return { ok: true, status: 201, json: () => Promise.resolve({ email: u.email, username: u.username, id, user_type: 'registered' }) };
  }
  if (apiPath === '/api/auth/me') {
    const m = auth.match(/Bearer (tok-(\d+))/);
    if (!m) return { ok: false, status: 401, json: () => Promise.resolve({ detail: 'no token' }) };
    const u = backend.users.get(Number(m[2]));
    if (!u) return { ok: false, status: 401, json: () => Promise.resolve({ detail: 'bad token' }) };
    return { ok: true, status: 200, json: () => Promise.resolve({ email: u.email, username: u.username, id: u.id, user_type: 'registered' }) };
  }
  if (apiPath === '/api/config') return { ok: true, status: 200, json: () => Promise.resolve({ google_client_id: null, streaming_enabled: false }) };
  if (apiPath === '/api/conversations') return { ok: true, status: 200, json: () => Promise.resolve([]) };
  if (apiPath === '/api/conversations/chat' && method === 'POST') {
    return { ok: true, status: 200, json: () => Promise.resolve({ conversation_id: 'c1', message: { id: 'm1', content: 'reply to: ' + (body.message || ''), role: 'assistant' } }) };
  }
  return { ok: true, status: 200, json: () => Promise.resolve({}) };
}

let fetchImpl = async (url, opts) => {
  const p = new URL(url, 'http://127.0.0.1:8000/').pathname;
  lastReq = { p, auth: (opts && opts.headers && opts.headers.Authorization) || null, body: opts && opts.body };
  const r = await handle(p, opts);
  return { ok: r.ok, status: r.status, json: r.json, text: async () => JSON.stringify(await r.json()), ...r };
};
window.fetch = fetchImpl;

// ---- run app.js ----
const ctx = vm.createContext({
  document,
  window,
  localStorage: window.localStorage,
  fetch: (url, opts) => fetchImpl(url, opts),
  AbortController: window.AbortController,
  TextDecoder,
  console,
  setTimeout,
  google: undefined,
  alert: window.alert,
  confirm: window.confirm,
  prompt: window.prompt,
  navigator: { userAgent: 'test' },
});
vm.runInContext(js, ctx, { filename: 'app.js' });

// ---- helpers ----
const results = [];
function check(name, cond, detail) {
  results.push({ name, pass: !!cond });
  console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name + (cond ? '' : (detail ? '  (' + detail + ')' : '')));
}
const click = (id) => document.getElementById(id).click();
function submitForm(formId) {
  document.getElementById(formId).dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await sleep(100);

  check('Boot with no token shows welcome view', document.getElementById('welcomeContainer').style.display !== 'none');

  // ---- Flow 1: Register + auto-login lands on chat page ----
  click('welcomeLoginBtn');
  check('Login button opens auth view', document.getElementById('authContainer').style.display === 'flex');

  document.getElementById('registerUsername').value = 'julius';
  document.getElementById('registerEmail').value = 'julius@example.com';
  document.getElementById('registerPassword').value = 'Passw0rd!';
  document.getElementById('registerConfirmPassword').value = 'Passw0rd!';
  submitForm('registerForm');
  await sleep(250);

  check('Register+auto-login lands on chat view (chatContainer active)', document.getElementById('chatContainer').classList.contains('active'));
  check('Register stores token', !!window.localStorage.getItem('token'));
  check('Chat title element rendered without error', typeof document.getElementById('chatTitle').textContent === 'string');
  check('User email shown in sidebar', document.getElementById('userEmail').textContent === 'julius@example.com');

  // ---- Flow 2: Logout ----
  click('logoutBtn');
  await sleep(30);
  check('Logout returns to welcome', document.getElementById('welcomeContainer').style.display !== 'none');
  check('Logout clears token', !window.localStorage.getItem('token'));

  // ---- Flow 3: Login again ----
  click('welcomeLoginBtn');
  document.getElementById('loginEmail').value = 'julius@example.com';
  document.getElementById('loginPassword').value = 'Passw0rd!';
  submitForm('loginForm');
  await sleep(250);
  check('Login lands on chat view (2nd time)', document.getElementById('chatContainer').classList.contains('active'));
  check('Login stores token (2nd time)', !!window.localStorage.getItem('token'));

  // ---- Flow 4: Guest must start completely fresh ----
  click('logoutBtn');
  await sleep(30);
  click('welcomeGuestBtn');
  await sleep(50);

  check('Guest mode: chat view active', document.getElementById('chatContainer').classList.contains('active'));
  check('Guest mode: token cleared from localStorage', !window.localStorage.getItem('token'));
  check('Guest mode: email shows "Guest"', document.getElementById('userEmail').textContent === 'Guest');
  check('Guest mode: avatar shows "G"', document.getElementById('userAvatar').textContent === 'G');
  check('Guest mode: guest banner visible', document.getElementById('guestBanner').style.display === 'flex');

  // Send a guest message and verify NO Authorization header is sent (no token leak)
  lastReq = null;
  document.getElementById('messageInput').value = 'hello guest';
  document.getElementById('sendBtn').click();
  await sleep(250);

  check('Guest message request sends NO Authorization header', !lastReq.auth, 'auth=' + lastReq.auth);
  check('Guest message request hit chat endpoint', lastReq.p === '/api/conversations/chat');

  const failed = results.filter((r) => !r.pass);
  console.log('\n' + (failed.length === 0 ? 'ALL TESTS PASSED (' + results.length + ')' : failed.length + ' OF ' + results.length + ' TESTS FAILED'));
  process.exit(failed.length === 0 ? 0 : 1);
})();
