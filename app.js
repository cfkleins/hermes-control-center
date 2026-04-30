const transcriptSamples = [
  "Open the dashboard and show current task queue.",
  "Summarize last 5 prompt executions.",
  "Switch voice profile to low-latency mode."
];

let sessionToken = localStorage.getItem("ops_ui_token") || "";
let activeOperator = localStorage.getItem("ops_ui_operator") || "";
let timelineIntervalId = null;

const headerDatetime = document.getElementById("header-datetime");

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

const authStatus = document.getElementById("auth-status");
const activeOperatorEl = document.getElementById("active-operator");
const usernameInput = document.getElementById("username-input");
const pinInput = document.getElementById("pin-input");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");

const refreshBtn = document.getElementById("refresh-metrics");
const tasksRunning = document.getElementById("tasks-running");
const avgResponse = document.getElementById("avg-response");
const errorRate = document.getElementById("error-rate");

const promptInput = document.getElementById("prompt-input");
const sendPrompt = document.getElementById("send-prompt");
const clearPrompt = document.getElementById("clear-prompt");
const promptStatus = document.getElementById("prompt-status");
const promptHistory = document.getElementById("prompt-history");

const startListening = document.getElementById("start-listening");
const stopListening = document.getElementById("stop-listening");
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

function setAuthUi() {
  activeOperatorEl.textContent = activeOperator || "(not logged in)";
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
    logout();
    throw new Error("Session expired/invalid. Please login again.");
  }
  if (!res.ok) throw new Error(`${url} failed: ${res.status}`);
  return res;
}

function logout() {
  sessionToken = "";
  activeOperator = "";
  localStorage.removeItem("ops_ui_token");
  localStorage.removeItem("ops_ui_operator");
  setAuthUi();
  authStatus.textContent = "Logged out.";
}

async function login() {
  const username = usernameInput.value.trim();
  const pin = pinInput.value.trim();
  if (!username || !pin) {
    authStatus.textContent = "Enter username and PIN.";
    return;
  }

  authStatus.textContent = "Logging in...";
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
    localStorage.setItem("ops_ui_token", sessionToken);
    localStorage.setItem("ops_ui_operator", activeOperator);
    setAuthUi();
    authStatus.textContent = `Logged in as ${activeOperator}.`;
    await bootstrapData();
  } catch (err) {
    console.error(err);
    authStatus.textContent = "Login failed.";
  }
}

loginBtn.addEventListener("click", login);
logoutBtn.addEventListener("click", logout);

async function refreshMetrics() {
  try {
    const res = await authFetch("/api/metrics");
    const data = await res.json();
    tasksRunning.textContent = String(data.tasks_running);
    avgResponse.textContent = `${data.avg_response_seconds}s`;
    errorRate.textContent = `${data.error_rate_percent}%`;
    document.getElementById("agent-status").textContent = `${data.agent_status} (${data.operator})`;
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
  recognition.onend = () => (micState.textContent = "Idle");
  recognition.onerror = () => (micState.textContent = "Error");
}

startListening.addEventListener("click", async () => {
  micState.textContent = "Listening";
  if (recognition) return recognition.start();
  const simulated = transcriptSamples[voicePointer];
  voicePointer = (voicePointer + 1) % transcriptSamples.length;
  transcript.textContent = simulated;
  await submitVoiceTranscript(simulated);
  micState.textContent = "Idle";
});

stopListening.addEventListener("click", () => {
  if (recognition) recognition.stop();
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
  alertsList.innerHTML = items.length
    ? items
        .map((item) => {
          const severityClass = `alert-${item.severity}`;
          return `<li class="${severityClass}"><strong>${item.severity.toUpperCase()}</strong> · ${item.message}<br><span class="status small">${item.code}</span></li>`;
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
    setAuthUi();
    authStatus.textContent = `Session restored for ${activeOperator}.`;
    await bootstrapData();
  } catch {
    logout();
  }
}

restoreSession();
