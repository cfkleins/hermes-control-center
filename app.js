const transcriptSamples = [
  "Open the dashboard and show current task queue.",
  "Summarize last 5 prompt executions.",
  "Switch voice profile to low-latency mode."
];

let sessionToken = localStorage.getItem("ops_ui_token") || "";
let activeOperator = localStorage.getItem("ops_ui_operator") || "";
let activeRole = localStorage.getItem("ops_ui_role") || "";
let sessionIdleTimeoutSeconds = Number(localStorage.getItem("ops_ui_session_idle_timeout") || 0);
let sessionAbsoluteTimeoutSeconds = Number(localStorage.getItem("ops_ui_session_absolute_timeout") || 0);
let sessionCreatedAtMs = Number(localStorage.getItem("ops_ui_session_created_at_ms") || 0);
let sessionLastTouchMs = Number(localStorage.getItem("ops_ui_session_last_touch_ms") || 0);
let sessionLastSeenAtIso = localStorage.getItem("ops_ui_session_last_seen_at") || "";
let sessionWarningShown = false;
let sessionCountdownIntervalId = null;
let timelineIntervalId = null;
const trendHistory = {
  tasks: [],
  response: [],
  error: []
};

const headerDatetime = document.getElementById("header-datetime");
const headerRoleBadge = document.getElementById("header-role-badge");
const activeTabLabel = document.getElementById("active-tab-label");
const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
const tabSections = Array.from(document.querySelectorAll(".tab-content"));

function updateHeaderDatetime() {
  if (!headerDatetime) return;
  const now = new Date();
  const date = now.toISOString().slice(0, 10); // yyyy-mm-dd
  const time = now.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit"
  });
  headerDatetime.textContent = `${date} ${time}`;
}

updateHeaderDatetime();
setInterval(updateHeaderDatetime, 1000);

function normalizeTabName(tabName) {
  const allowed = new Set(["operations", "prompt-voice"]);
  return allowed.has(tabName) ? tabName : "operations";
}

function activeTabDisplayName(tabName) {
  return tabName === "prompt-voice" ? "Prompt and Voice" : "Operations";
}

function activateTab(tabName, { persist = true } = {}) {
  const normalized = normalizeTabName(tabName);
  tabButtons.forEach((btn) => {
    const isActive = btn.dataset.tab === normalized;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
  });
  tabSections.forEach((section) => {
    section.classList.toggle("active", section.dataset.tabSection === normalized);
  });
  if (activeTabLabel) {
    activeTabLabel.textContent = `Active Section: ${activeTabDisplayName(normalized)}`;
  }
  if (persist) {
    localStorage.setItem("ops_ui_active_tab", normalized);
    history.replaceState(null, "", `#${normalized}`);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab || "operations"));
});

const initialTabFromHash = (window.location.hash || "").replace("#", "");
const initialTabFromStorage = localStorage.getItem("ops_ui_active_tab") || "operations";
activateTab(initialTabFromHash || initialTabFromStorage, { persist: false });

window.addEventListener("hashchange", () => {
  const tab = (window.location.hash || "").replace("#", "");
  if (tab) activateTab(tab);
});

window.addEventListener("keydown", (event) => {
  const tagName = document.activeElement?.tagName || "";
  const isTypingTarget = ["INPUT", "TEXTAREA", "SELECT"].includes(tagName);
  if (isTypingTarget || event.ctrlKey || event.metaKey || event.altKey) return;

  if (event.key === "1") {
    activateTab("operations");
  } else if (event.key === "2") {
    activateTab("prompt-voice");
  }
});

const authStatus = document.getElementById("auth-status");
const activeOperatorEl = document.getElementById("active-operator");
const usernameInput = document.getElementById("username-input");
const pinInput = document.getElementById("pin-input");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");

const pvAuthStatus = document.getElementById("pv-auth-status");
const pvActiveOperatorEl = document.getElementById("pv-active-operator");
const pvUsernameInput = document.getElementById("pv-username-input");
const pvPinInput = document.getElementById("pv-pin-input");
const pvLoginBtn = document.getElementById("pv-login-btn");
const pvLogoutBtn = document.getElementById("pv-logout-btn");
const pvRefreshBtn = document.getElementById("pv-refresh-btn");
const sessionCountdownEl = document.getElementById("session-countdown");
const pvSessionCountdownEl = document.getElementById("pv-session-countdown");
const sessionLastActivityEl = document.getElementById("session-last-activity");
const pvSessionLastActivityEl = document.getElementById("pv-session-last-activity");

const refreshBtn = document.getElementById("refresh-metrics");
const tasksRunning = document.getElementById("tasks-running");
const avgResponse = document.getElementById("avg-response");
const errorRate = document.getElementById("error-rate");
const trendTasks = document.getElementById("trend-tasks");
const trendResponse = document.getElementById("trend-response");
const trendError = document.getElementById("trend-error");
const trendTasksSpark = document.getElementById("trend-tasks-spark");
const trendResponseSpark = document.getElementById("trend-response-spark");
const trendErrorSpark = document.getElementById("trend-error-spark");

const promptInput = document.getElementById("prompt-input");
const sendPrompt = document.getElementById("send-prompt");
const clearPrompt = document.getElementById("clear-prompt");
const promptStatus = document.getElementById("prompt-status");
const promptHistory = document.getElementById("prompt-history");
const templateNameInput = document.getElementById("template-name-input");
const templatePromptInput = document.getElementById("template-prompt-input");
const saveTemplateBtn = document.getElementById("save-template");
const refreshTemplatesBtn = document.getElementById("refresh-templates");
const templateList = document.getElementById("template-list");

const startListening = document.getElementById("start-listening");
const stopListening = document.getElementById("stop-listening");
const vadEnabled = document.getElementById("vad-enabled");
const vadSilenceMsInput = document.getElementById("vad-silence-ms");
const vadState = document.getElementById("vad-state");
const micState = document.getElementById("mic-state");
const transcript = document.getElementById("transcript");
const voiceLastAction = document.getElementById("voice-last-action");
const voiceEvents = document.getElementById("voice-events");

const timelineFilter = document.getElementById("timeline-filter");
const refreshTimelineBtn = document.getElementById("refresh-timeline");
const timelineEvents = document.getElementById("timeline-events");

const refreshAlertsBtn = document.getElementById("refresh-alerts");
const alertsList = document.getElementById("alerts-list");

const providerInput = document.getElementById("provider-input");
const modelInput = document.getElementById("model-input");
const voiceProfileSelect = document.getElementById("voice-profile-select");
const timelineRefreshInput = document.getElementById("timeline-refresh-input");
const saveSettingsBtn = document.getElementById("save-settings");
const reloadSettingsBtn = document.getElementById("reload-settings");
const settingsStatus = document.getElementById("settings-status");

let voicePointer = 0;
let vadAudioContext = null;
let vadMediaStream = null;
let vadAnalyser = null;
let vadSource = null;
let vadRafId = null;
let vadLastSpeechAt = 0;
let isListeningActive = false;

function formatRemainingSeconds(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const mm = String(Math.floor(safe / 60)).padStart(2, "0");
  const ss = String(safe % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function setSessionCountdownText(message) {
  if (sessionCountdownEl) sessionCountdownEl.textContent = message;
  if (pvSessionCountdownEl) pvSessionCountdownEl.textContent = message;
}

function setSessionLastActivityText(message) {
  if (sessionLastActivityEl) sessionLastActivityEl.textContent = message;
  if (pvSessionLastActivityEl) pvSessionLastActivityEl.textContent = message;
}

function parseIsoMs(value) {
  if (!value) return 0;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : 0;
}

function renderLastActivity() {
  if (!sessionLastSeenAtIso) {
    setSessionLastActivityText("Last activity: --");
    return;
  }
  const d = new Date(sessionLastSeenAtIso);
  if (Number.isNaN(d.getTime())) {
    setSessionLastActivityText("Last activity: --");
    return;
  }
  setSessionLastActivityText(`Last activity: ${d.toLocaleString()}`);
}

async function logoutRemote() {
  if (!sessionToken) return;
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "X-Session-Token": sessionToken }
    });
  } catch (err) {
    console.warn("logout remote failed", err);
  }
}

function touchSessionTimer() {
  if (!sessionToken || !sessionIdleTimeoutSeconds) return;
  sessionLastTouchMs = Date.now();
  sessionLastSeenAtIso = new Date(sessionLastTouchMs).toISOString();
  localStorage.setItem("ops_ui_session_last_touch_ms", String(sessionLastTouchMs));
  localStorage.setItem("ops_ui_session_last_seen_at", sessionLastSeenAtIso);
  renderLastActivity();
}

function startSessionCountdown() {
  if (sessionCountdownIntervalId) clearInterval(sessionCountdownIntervalId);
  if (!sessionToken || !sessionIdleTimeoutSeconds) {
    setSessionCountdownText("Session timeout: --");
    return;
  }

  const tick = () => {
    const nowMs = Date.now();
    const idleRemainingSec = sessionIdleTimeoutSeconds - Math.floor((nowMs - sessionLastTouchMs) / 1000);
    const absoluteRemainingSec = sessionAbsoluteTimeoutSeconds > 0 && sessionCreatedAtMs > 0
      ? sessionAbsoluteTimeoutSeconds - Math.floor((nowMs - sessionCreatedAtMs) / 1000)
      : Number.POSITIVE_INFINITY;
    const remainingSec = Math.min(idleRemainingSec, absoluteRemainingSec);

    if (remainingSec <= 0) {
      setSessionCountdownText("Session timeout: expired");
      void logout({ localOnly: false, reason: "Session expired (idle or max lifetime)." });
      return;
    }

    if (remainingSec <= 60 && !sessionWarningShown) {
      sessionWarningShown = true;
      setAuthStatus(`Warning: session expires in ${formatRemainingSeconds(remainingSec)}.`);
    }

    setSessionCountdownText(`Session timeout: ${formatRemainingSeconds(remainingSec)}`);
  };

  tick();
  sessionCountdownIntervalId = setInterval(tick, 1000);
}

function applySessionMetadata(data = {}) {
  const ttl = Number(data.session_idle_timeout_seconds || 0);
  const absoluteTtl = Number(data.session_absolute_timeout_seconds || 0);
  sessionIdleTimeoutSeconds = Number.isFinite(ttl) && ttl > 0 ? ttl : 0;
  sessionAbsoluteTimeoutSeconds = Number.isFinite(absoluteTtl) && absoluteTtl > 0 ? absoluteTtl : 0;

  const absoluteExpiryMs = parseIsoMs(data.session_absolute_expires_at);
  sessionCreatedAtMs = absoluteExpiryMs > 0 && sessionAbsoluteTimeoutSeconds > 0
    ? absoluteExpiryMs - sessionAbsoluteTimeoutSeconds * 1000
    : Date.now();

  const serverLastSeenMs = parseIsoMs(data.session_last_seen_at);
  if (serverLastSeenMs > 0) {
    sessionLastTouchMs = serverLastSeenMs;
    sessionLastSeenAtIso = new Date(serverLastSeenMs).toISOString();
  } else {
    touchSessionTimer();
  }

  localStorage.setItem("ops_ui_session_idle_timeout", String(sessionIdleTimeoutSeconds));
  localStorage.setItem("ops_ui_session_absolute_timeout", String(sessionAbsoluteTimeoutSeconds));
  localStorage.setItem("ops_ui_session_created_at_ms", String(sessionCreatedAtMs));
  localStorage.setItem("ops_ui_session_last_touch_ms", String(sessionLastTouchMs));
  localStorage.setItem("ops_ui_session_last_seen_at", sessionLastSeenAtIso || "");

  sessionWarningShown = false;
  renderLastActivity();
  startSessionCountdown();
}

function setSessionInfoLoggedOut() {
  if (sessionCountdownIntervalId) {
    clearInterval(sessionCountdownIntervalId);
    sessionCountdownIntervalId = null;
  }
  setSessionCountdownText("Session timeout: --");
  setSessionLastActivityText("Last activity: --");
}

function setAuthUi() {
  const operatorLabel = activeOperator || "(not logged in)";
  activeOperatorEl.textContent = operatorLabel;
  if (pvActiveOperatorEl) pvActiveOperatorEl.textContent = operatorLabel;

  const isAdmin = activeRole === "admin";
  [providerInput, modelInput, voiceProfileSelect, timelineRefreshInput].forEach((el) => {
    if (el) el.disabled = !activeOperator || !isAdmin;
  });
  if (saveSettingsBtn) saveSettingsBtn.disabled = !activeOperator || !isAdmin;

  if (headerRoleBadge) {
    const normalizedRole = activeOperator ? (activeRole || "operator") : "none";
    headerRoleBadge.textContent = `ROLE: ${normalizedRole.toUpperCase()}`;
    headerRoleBadge.classList.remove("role-admin", "role-operator", "role-none");
    headerRoleBadge.classList.add(
      normalizedRole === "admin" ? "role-admin" : normalizedRole === "operator" ? "role-operator" : "role-none"
    );
  }

  if (!activeOperator) {
    authStatus.textContent = "Please log in.";
    if (pvAuthStatus) pvAuthStatus.textContent = "Please log in.";
    if (settingsStatus) settingsStatus.textContent = "Login required.";
  } else if (!isAdmin) {
    if (settingsStatus) settingsStatus.textContent = "Read-only: operator role cannot modify settings.";
  }
}

async function authFetch(url, options = {}) {
  if (!sessionToken) {
    throw new Error("No active session. Please login.");
  }
  const headers = {
    ...(options.headers || {}),
    "X-Session-Token": sessionToken
  };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    await logout({ localOnly: true, reason: "Session expired/invalid. Please login again." });
    throw new Error("Session expired/invalid. Please login again.");
  }
  if (!res.ok) throw new Error(`${url} failed: ${res.status}`);
  touchSessionTimer();
  return res;
}

function setAuthStatus(message) {
  authStatus.textContent = message;
  if (pvAuthStatus) pvAuthStatus.textContent = message;
}

async function logout({ localOnly = false, reason = "Logged out." } = {}) {
  if (!localOnly) {
    await logoutRemote();
  }
  sessionToken = "";
  activeOperator = "";
  activeRole = "";
  sessionIdleTimeoutSeconds = 0;
  sessionAbsoluteTimeoutSeconds = 0;
  sessionCreatedAtMs = 0;
  sessionLastTouchMs = 0;
  sessionLastSeenAtIso = "";
  sessionWarningShown = false;
  localStorage.removeItem("ops_ui_token");
  localStorage.removeItem("ops_ui_operator");
  localStorage.removeItem("ops_ui_role");
  localStorage.removeItem("ops_ui_session_idle_timeout");
  localStorage.removeItem("ops_ui_session_absolute_timeout");
  localStorage.removeItem("ops_ui_session_created_at_ms");
  localStorage.removeItem("ops_ui_session_last_touch_ms");
  localStorage.removeItem("ops_ui_session_last_seen_at");
  setSessionInfoLoggedOut();
  setAuthUi();
  setAuthStatus(reason);
}

async function login(credentials = null) {
  const username = (credentials?.username ?? usernameInput.value).trim();
  const pin = (credentials?.pin ?? pinInput.value).trim();
  if (!username || !pin) {
    setAuthStatus("Enter username and PIN.");
    return;
  }

  setAuthStatus("Logging in...");
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, pin })
    });
    if (!res.ok) throw new Error(`login failed: ${res.status}`);
    const data = await res.json();
    sessionToken = data.token;
    activeOperator = data.username;
    activeRole = data.role || "operator";
    localStorage.setItem("ops_ui_token", sessionToken);
    localStorage.setItem("ops_ui_operator", activeOperator);
    localStorage.setItem("ops_ui_role", activeRole);
    applySessionMetadata(data);
    usernameInput.value = activeOperator;
    if (pvUsernameInput) pvUsernameInput.value = activeOperator;
    pinInput.value = "";
    if (pvPinInput) pvPinInput.value = "";
    setAuthUi();
    setAuthStatus(`Logged in as ${activeOperator} (${activeRole}).`);
    await bootstrapData();
  } catch (err) {
    console.error(err);
    setAuthStatus("Login failed.");
  }
}

loginBtn.addEventListener("click", () => login());
logoutBtn.addEventListener("click", () => logout());
if (pvLoginBtn) {
  pvLoginBtn.addEventListener("click", () =>
    login({
      username: pvUsernameInput?.value || "",
      pin: pvPinInput?.value || ""
    })
  );
}
if (pvLogoutBtn) pvLogoutBtn.addEventListener("click", () => logout());
if (pvRefreshBtn) {
  pvRefreshBtn.addEventListener("click", async () => {
    if (!sessionToken) return setAuthStatus("Please log in first.");
    await loadPromptHistory();
    await loadTemplates();
    await loadVoiceEvents();
    await loadTimeline();
    setAuthStatus("Prompt & Voice data refreshed.");
  });
}

function sparkline(history) {
  if (!history.length) return "--";
  const bars = "▁▂▃▄▅▆▇█";
  const nums = history.map((v) => Number(v));
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  if (max === min) {
    return bars[3].repeat(nums.length);
  }
  return nums
    .map((v) => {
      const normalized = (v - min) / (max - min);
      const idx = Math.max(0, Math.min(bars.length - 1, Math.round(normalized * (bars.length - 1))));
      return bars[idx];
    })
    .join("");
}

function trendClassForHistory(history, { lowerIsBetter = false } = {}) {
  if (!history || history.length < 2) return "trend-flat";
  const prev = Number(history[history.length - 2]);
  const last = Number(history[history.length - 1]);
  if (last === prev) return "trend-flat";
  const improved = lowerIsBetter ? last < prev : last > prev;
  return improved ? "trend-good" : "trend-bad";
}

function applyTrendClass(element, className) {
  if (!element) return;
  element.classList.remove("trend-good", "trend-bad", "trend-flat");
  element.classList.add(className);
}

function pushTrend(history, value, max = 12) {
  history.push(value);
  if (history.length > max) history.shift();
}

function renderTrend(history, decimals = 0) {
  if (!history.length) return "--";
  return history.map((value) => Number(value).toFixed(decimals)).join(" · ");
}

function updateKpiTrendStrip(data) {
  pushTrend(trendHistory.tasks, Number(data.tasks_running || 0));
  pushTrend(trendHistory.response, Number(data.avg_response_seconds || 0));
  pushTrend(trendHistory.error, Number(data.error_rate_percent || 0));

  if (trendTasks) trendTasks.textContent = renderTrend(trendHistory.tasks, 0);
  if (trendResponse) trendResponse.textContent = renderTrend(trendHistory.response, 2);
  if (trendError) trendError.textContent = renderTrend(trendHistory.error, 2);

  if (trendTasksSpark) {
    trendTasksSpark.textContent = sparkline(trendHistory.tasks);
    applyTrendClass(trendTasksSpark, trendClassForHistory(trendHistory.tasks, { lowerIsBetter: true }));
  }
  if (trendResponseSpark) {
    trendResponseSpark.textContent = sparkline(trendHistory.response);
    applyTrendClass(trendResponseSpark, trendClassForHistory(trendHistory.response, { lowerIsBetter: true }));
  }
  if (trendErrorSpark) {
    trendErrorSpark.textContent = sparkline(trendHistory.error);
    applyTrendClass(trendErrorSpark, trendClassForHistory(trendHistory.error, { lowerIsBetter: true }));
  }
}

async function refreshMetrics() {
  try {
    const res = await authFetch("/api/metrics");
    const data = await res.json();
    tasksRunning.textContent = String(data.tasks_running);
    avgResponse.textContent = `${data.avg_response_seconds}s`;
    errorRate.textContent = `${data.error_rate_percent}%`;
    document.getElementById("agent-status").textContent = `${data.agent_status} (${data.operator})`;
    updateKpiTrendStrip(data);
  } catch (err) {
    console.error(err);
  }
}

refreshBtn.addEventListener("click", async () => {
  await refreshMetrics();
  await loadAlerts();
  await loadTimeline();
});

function renderPromptHistory(items) {
  promptHistory.innerHTML = items.length
    ? items
        .map(
          (item) =>
            `<li><strong>#${item.id}</strong> · ${item.status} · attempts: ${item.attempts}<br>${item.prompt.slice(0, 90)}</li>`
        )
        .join("")
    : '<li class="status small">No prompt runs yet.</li>';
}

async function loadPromptHistory() {
  try {
    const res = await authFetch("/api/prompts?limit=8");
    const data = await res.json();
    renderPromptHistory(data.items || []);
  } catch (err) {
    console.error(err);
  }
}

function renderTemplates(items) {
  const isAdmin = activeRole === "admin";
  templateList.innerHTML = items.length
    ? items
        .map(
          (item) => `<li>
            <strong>${item.name}</strong><br>
            ${item.prompt.slice(0, 140)}
            <div class="row alert-actions">
              <button class="ghost" data-template-use="${item.id}">Use</button>
              <button class="ghost" data-template-delete="${item.id}" ${isAdmin ? "" : "disabled"}>Delete</button>
            </div>
          </li>`
        )
        .join("")
    : '<li class="status small">No templates yet.</li>';
}

async function loadTemplates() {
  try {
    const res = await authFetch("/api/prompt-templates?limit=25");
    const data = await res.json();
    renderTemplates(data.items || []);
  } catch (err) {
    console.error(err);
  }
}

async function saveTemplate() {
  const name = templateNameInput.value.trim();
  const prompt = templatePromptInput.value.trim();
  if (!name || !prompt) return;
  try {
    await authFetch("/api/prompt-templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt })
    });
    templateNameInput.value = "";
    templatePromptInput.value = "";
    await loadTemplates();
    await loadTimeline();
  } catch (err) {
    console.error(err);
  }
}

sendPrompt.addEventListener("click", async () => {
  const value = promptInput.value.trim();
  if (!value) return (promptStatus.textContent = "Please enter a prompt first.");
  promptStatus.textContent = "Submitting prompt...";
  try {
    const res = await authFetch("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: value })
    });
    const data = await res.json();
    promptStatus.textContent = `Prompt #${data.id} ${data.status} (attempts: ${data.attempts})`;
    await loadPromptHistory();
    await loadTimeline();
  } catch {
    promptStatus.textContent = "Prompt submission failed.";
  }
});

clearPrompt.addEventListener("click", () => {
  promptInput.value = "";
  promptStatus.textContent = "Prompt cleared.";
});

saveTemplateBtn.addEventListener("click", saveTemplate);
refreshTemplatesBtn.addEventListener("click", loadTemplates);
templateList.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const useId = target.getAttribute("data-template-use");
  const deleteId = target.getAttribute("data-template-delete");
  if (useId) {
    try {
      const res = await authFetch("/api/prompt-templates?limit=25");
      const data = await res.json();
      const match = (data.items || []).find((item) => item.id === Number(useId));
      if (match) {
        promptInput.value = match.prompt;
        promptStatus.textContent = `Template loaded: ${match.name}`;
      }
    } catch (err) {
      console.error(err);
    }
  }
  if (deleteId) {
    if (activeRole !== "admin") {
      promptStatus.textContent = "Delete requires admin role.";
      return;
    }
    try {
      await authFetch(`/api/prompt-templates/${deleteId}`, { method: "DELETE" });
      await loadTemplates();
      await loadTimeline();
    } catch (err) {
      console.error(err);
    }
  }
});

function renderVoiceEvents(items) {
  voiceEvents.innerHTML = items.length
    ? items
        .map(
          (item) =>
            `<li><strong>#${item.id}</strong> · ${item.action}<br>${item.transcript.slice(0, 100)}<br><span class="status small">${item.result}</span></li>`
        )
        .join("")
    : '<li class="status small">No voice events yet.</li>';
}

async function loadVoiceEvents() {
  try {
    const res = await authFetch("/api/voice/events?limit=8");
    const data = await res.json();
    renderVoiceEvents(data.items || []);
  } catch (err) {
    console.error(err);
  }
}

async function submitVoiceTranscript(text) {
  try {
    const res = await authFetch("/api/voice/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: text })
    });
    const data = await res.json();
    voiceLastAction.textContent = `${data.action} (${data.status})`;
    await loadVoiceEvents();
    await loadTimeline();
  } catch {
    voiceLastAction.textContent = "submit_failed";
  }
}

function stopVadMonitor() {
  if (vadRafId) {
    cancelAnimationFrame(vadRafId);
    vadRafId = null;
  }
  if (vadSource) {
    try { vadSource.disconnect(); } catch {}
    vadSource = null;
  }
  if (vadMediaStream) {
    vadMediaStream.getTracks().forEach((t) => t.stop());
    vadMediaStream = null;
  }
  if (vadAudioContext) {
    try { vadAudioContext.close(); } catch {}
    vadAudioContext = null;
  }
  vadAnalyser = null;
  if (vadState) vadState.textContent = "Inactive";
}

async function startVadMonitor() {
  if (!vadEnabled?.checked) return;
  stopVadMonitor();
  try {
    vadMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    vadAudioContext = new AudioContext();
    vadSource = vadAudioContext.createMediaStreamSource(vadMediaStream);
    vadAnalyser = vadAudioContext.createAnalyser();
    vadAnalyser.fftSize = 1024;
    vadSource.connect(vadAnalyser);

    const buffer = new Uint8Array(vadAnalyser.fftSize);
    const silenceMs = Number(vadSilenceMsInput?.value || 1200);
    const threshold = 0.018;
    vadLastSpeechAt = Date.now();
    if (vadState) vadState.textContent = "Monitoring";

    const tick = () => {
      if (!isListeningActive || !vadAnalyser) return;
      vadAnalyser.getByteTimeDomainData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i += 1) {
        const centered = (buffer[i] - 128) / 128;
        sum += centered * centered;
      }
      const rms = Math.sqrt(sum / buffer.length);
      const now = Date.now();

      if (rms > threshold) {
        vadLastSpeechAt = now;
        if (vadState) vadState.textContent = "Speech detected";
      } else if (now - vadLastSpeechAt > silenceMs) {
        if (vadState) vadState.textContent = "Silence detected → stopping";
        if (recognition) recognition.stop();
        stopVadMonitor();
        return;
      } else if (vadState) {
        vadState.textContent = "Listening for speech";
      }

      vadRafId = requestAnimationFrame(tick);
    };

    vadRafId = requestAnimationFrame(tick);
  } catch (err) {
    console.error(err);
    if (vadState) vadState.textContent = "Unavailable";
  }
}

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onresult = async (event) => {
    const spoken = event.results[0][0].transcript.trim();
    transcript.textContent = spoken;
    await submitVoiceTranscript(spoken);
  };
  recognition.onend = () => {
    isListeningActive = false;
    micState.textContent = "Idle";
    stopVadMonitor();
  };
  recognition.onerror = () => {
    isListeningActive = false;
    micState.textContent = "Error";
    stopVadMonitor();
  };
}

startListening.addEventListener("click", async () => {
  micState.textContent = "Listening";
  if (recognition) {
    isListeningActive = true;
    await startVadMonitor();
    return recognition.start();
  }
  const simulated = transcriptSamples[voicePointer];
  voicePointer = (voicePointer + 1) % transcriptSamples.length;
  transcript.textContent = simulated;
  await submitVoiceTranscript(simulated);
  micState.textContent = "Idle";
});

stopListening.addEventListener("click", () => {
  isListeningActive = false;
  if (recognition) recognition.stop();
  stopVadMonitor();
  micState.textContent = "Idle";
  transcript.textContent = "(waiting)";
});

function renderTimeline(items) {
  timelineEvents.innerHTML = items.length
    ? items
        .map((item) => {
          const t = new Date(item.created_at).toLocaleTimeString();
          return `<li><strong>[${item.kind}]</strong> ${item.message}<br><span class="status small">${t}</span></li>`;
        })
        .join("")
    : '<li class="status small">No timeline events yet.</li>';
}

function renderAlerts(items) {
  const isAdmin = activeRole === "admin";
  alertsList.innerHTML = items.length
    ? items
        .map((item) => {
          const severityClass = `alert-${item.severity}`;
          const actionState = item.action_state || "open";
          return `<li class="${severityClass}">
            <strong>${item.severity.toUpperCase()}</strong> · ${item.message}<br>
            <span class="status small">${item.code} · ${actionState}</span>
            <div class="row alert-actions">
              <button class="ghost" data-alert-id="${item.id}" data-alert-action="ack" ${isAdmin ? "" : "disabled"}>Ack</button>
              <button class="ghost" data-alert-id="${item.id}" data-alert-action="snooze" ${isAdmin ? "" : "disabled"}>Snooze</button>
              <button class="ghost" data-alert-id="${item.id}" data-alert-action="resolve" ${isAdmin ? "" : "disabled"}>Resolve</button>
            </div>
          </li>`;
        })
        .join("")
    : '<li class="status small">No alerts yet.</li>';
}

async function loadAlerts() {
  try {
    const res = await authFetch("/api/alerts?limit=6");
    const data = await res.json();
    renderAlerts(data.items || []);
  } catch (err) {
    console.error(err);
  }
}

async function applyAlertAction(alertId, action) {
  if (activeRole !== "admin") {
    setAuthStatus("Alert actions require admin role.");
    return;
  }
  try {
    await authFetch(`/api/alerts/${alertId}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    await loadAlerts();
    await loadTimeline();
  } catch (err) {
    console.error(err);
  }
}

async function loadTimeline() {
  try {
    const kind = timelineFilter ? timelineFilter.value : "all";
    const res = await authFetch(`/api/timeline?limit=15&kind=${encodeURIComponent(kind)}`);
    const data = await res.json();
    renderTimeline(data.items || []);
  } catch (err) {
    console.error(err);
  }
}

function startTimelineAutoRefresh(seconds) {
  if (timelineIntervalId) clearInterval(timelineIntervalId);
  timelineIntervalId = setInterval(loadTimeline, seconds * 1000);
}

timelineFilter.addEventListener("change", loadTimeline);
refreshTimelineBtn.addEventListener("click", loadTimeline);
refreshAlertsBtn.addEventListener("click", loadAlerts);
alertsList.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const action = target.getAttribute("data-alert-action");
  const alertId = target.getAttribute("data-alert-id");
  if (!action || !alertId) return;
  await applyAlertAction(Number(alertId), action);
});

function applySettingsToUi(settings) {
  providerInput.value = settings.provider || "openai";
  modelInput.value = settings.model || "gpt-5.3-codex";
  voiceProfileSelect.value = settings.voice_profile || "quality";
  timelineRefreshInput.value = String(settings.timeline_refresh_seconds || 5);
  startTimelineAutoRefresh(Number(settings.timeline_refresh_seconds || 5));
}

async function loadSettings() {
  try {
    const res = await authFetch("/api/settings");
    const data = await res.json();
    applySettingsToUi(data);
    settingsStatus.textContent = "Settings loaded.";
  } catch {
    settingsStatus.textContent = "Failed to load settings.";
  }
}

async function saveSettings() {
  if (activeRole !== "admin") {
    settingsStatus.textContent = "Read-only: admin role required to save settings.";
    return;
  }
  const payload = {
    provider: providerInput.value.trim(),
    model: modelInput.value.trim(),
    voice_profile: voiceProfileSelect.value,
    timeline_refresh_seconds: Number(timelineRefreshInput.value)
  };
  settingsStatus.textContent = "Saving settings...";
  try {
    const res = await authFetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    applySettingsToUi(data);
    settingsStatus.textContent = "Settings saved.";
    await loadTimeline();
  } catch {
    settingsStatus.textContent = "Failed to save settings.";
  }
}

saveSettingsBtn.addEventListener("click", saveSettings);
reloadSettingsBtn.addEventListener("click", loadSettings);

async function bootstrapData() {
  await refreshMetrics();
  await loadPromptHistory();
  await loadTemplates();
  await loadVoiceEvents();
  await loadAlerts();
  await loadTimeline();
  await loadSettings();
}

async function restoreSession() {
  setAuthUi();
  if (!sessionToken) return;
  try {
    const res = await authFetch("/api/auth/me");
    const me = await res.json();
    activeOperator = me.username;
    activeRole = me.role || "operator";
    localStorage.setItem("ops_ui_role", activeRole);
    applySessionMetadata(me);
    setAuthUi();
    authStatus.textContent = `Session restored for ${activeOperator} (${activeRole}).`;
    await bootstrapData();
  } catch {
    await logout({ localOnly: true, reason: "Session restore failed. Please log in." });
  }
}

if (sessionToken && sessionIdleTimeoutSeconds > 0 && sessionLastTouchMs > 0) {
  renderLastActivity();
  startSessionCountdown();
} else {
  setSessionInfoLoggedOut();
}

restoreSession();
