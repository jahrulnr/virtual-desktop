import RFB from "/novnc/core/rfb.js";

const screen = document.querySelector("#desktop-screen");
const placeholder = document.querySelector("#feed-placeholder");
const connectionDot = document.querySelector("#connection-dot");
const connectionLabel = document.querySelector("#connection-label");
const leaseOwner = document.querySelector("#lease-owner");
const leaseDetail = document.querySelector("#lease-detail");
const operatorLabel = document.querySelector("#operator-label");
const takeControl = document.querySelector("#take-control");
const releaseControl = document.querySelector("#release-control");
const drawer = document.querySelector("#control-drawer");
const openTools = document.querySelector("#open-tools");
const closeTools = document.querySelector("#close-tools");
const credentialsDialog = document.querySelector("#credentials-dialog");
const credentialsForm = document.querySelector("#credentials-form");
const passwordInput = document.querySelector("#vnc-password");
const announcer = document.querySelector("#announcer");
const approvalForm = document.querySelector("#approval-form");
const approvalOutput = document.querySelector("#approval-output");
const installKind = document.querySelector("#install-kind");
const installValue = document.querySelector("#install-value");
const installValueLabel = document.querySelector("#install-value-label");
const agentDrawer = document.querySelector("#agent-drawer");
const openAgent = document.querySelector("#open-agent");
const closeAgent = document.querySelector("#close-agent");
const agentStatus = document.querySelector("#agent-status");
const agentStatusLabel = document.querySelector("#agent-status-label");
const agentTranscript = document.querySelector("#agent-transcript");
const agentEmpty = document.querySelector("#agent-empty");
const agentForm = document.querySelector("#agent-form");
const agentPrompt = document.querySelector("#agent-prompt");
const agentSend = document.querySelector("#agent-send");
const agentStop = document.querySelector("#agent-stop");
const permissionCard = document.querySelector("#permission-card");
const permissionTitle = document.querySelector("#permission-title");
const permissionDetail = document.querySelector("#permission-detail");
const permissionAllow = document.querySelector("#permission-allow");
const permissionReject = document.querySelector("#permission-reject");
const MAX_STREAM_BYTES = 8 * 1024 * 1024;
const MAX_EVENT_CHARS = 256 * 1024;
const MAX_ASSISTANT_CHARS = 256 * 1024;
const MAX_TRANSCRIPT_ITEMS = 200;
const sessionId = crypto.randomUUID();
const storedAgentSession = localStorage.getItem("relay.coddy.session");
const agentSessionId = /^sess_[0-9a-f]{16,64}$/.test(storedAgentSession || "")
  ? storedAgentSession
  : `sess_${crypto.randomUUID().replaceAll("-", "")}`;
localStorage.setItem("relay.coddy.session", agentSessionId);
let rfb;
let reconnectTimer;
let hasConnected = false;
let humanToken = "";
let agentAbort;
let pendingPermission;
let agentHistoryLoaded = false;
const permissionQueue = [];

function websocketUrl() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/websockify`;
}

function setConnection(state, label) {
  connectionDot.className = `status-dot ${state}`;
  connectionLabel.textContent = label;
}

function connect() {
  clearTimeout(reconnectTimer);
  if (rfb) {
    try { rfb.disconnect(); } catch { /* The transport is already gone. */ }
  }
  setConnection("", "Connecting");
  rfb = new RFB(screen, websocketUrl(), { shared: true });
  rfb.scaleViewport = true;
  rfb.resizeSession = false;
  rfb.viewOnly = true;
  rfb.qualityLevel = 7;
  rfb.compressionLevel = 3;

  rfb.addEventListener("connect", () => {
    hasConnected = true;
    placeholder?.remove();
    setConnection("connected", "Signal live");
    announcer.textContent = "Remote desktop connected";
  });
  rfb.addEventListener("credentialsrequired", () => {
    if (!credentialsDialog.open) credentialsDialog.showModal();
    passwordInput.focus();
  });
  rfb.addEventListener("securityfailure", () => {
    setConnection("failed", "Password rejected");
    humanToken = "";
    passwordInput.value = "";
    if (!credentialsDialog.open) credentialsDialog.showModal();
  });
  rfb.addEventListener("disconnect", (event) => {
    hasConnected = false;
    setConnection("failed", event.detail.clean ? "Signal closed" : "Signal lost");
    if (!event.detail.clean) reconnectTimer = setTimeout(connect, 2000);
  });
}

credentialsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const password = passwordInput.value;
  if (!password || !rfb) return;
  humanToken = password;
  rfb.sendCredentials({ password });
  passwordInput.value = "";
  credentialsDialog.close();
  refreshAgentHealth();
  loadAgentHistory();
});

async function api(path, options = {}) {
  const { human = false, headers = {}, ...request } = options;
  const response = await fetch(path, {
    ...request,
    headers: {
      "Content-Type": "application/json",
      ...(human && humanToken ? { "X-Human-Control-Token": humanToken } : {}),
      ...headers,
    },
  });
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(body?.error?.message || `Request failed (${response.status})`);
  return body;
}

function renderLease(state) {
  const isOurs = state.owner === "human" && state.ownerId === sessionId;
  document.body.dataset.owner = isOurs ? "human-self" : state.owner;
  takeControl.disabled = isOurs;
  releaseControl.disabled = !isOurs;
  if (rfb) rfb.viewOnly = !isOurs;

  if (isOurs) {
    leaseOwner.textContent = "You";
    leaseDetail.textContent = "Keyboard and pointer are live";
    operatorLabel.textContent = "Human control active";
  } else if (state.owner === "agent") {
    leaseOwner.textContent = "AI operator";
    leaseDetail.textContent = "Watching the agent work";
    operatorLabel.textContent = "AI is operating";
  } else if (state.owner === "human") {
    leaseOwner.textContent = "Another viewer";
    leaseDetail.textContent = "This feed is view-only";
    operatorLabel.textContent = "Another viewer has control";
  } else {
    leaseOwner.textContent = "Observer";
    leaseDetail.textContent = "No input is being sent";
    operatorLabel.textContent = "Desktop ready";
  }
}

async function refreshLease() {
  try {
    renderLease(await api("/api/v1/control", { method: "GET", headers: {} }));
  } catch (error) {
    leaseDetail.textContent = error.message;
  }
}

takeControl.addEventListener("click", async () => {
  try {
    const state = await api("/api/v1/control/human/claim", {
      method: "POST",
      human: true,
      body: JSON.stringify({ sessionId }),
    });
    renderLease(state);
    screen.focus();
    announcer.textContent = "You now control the remote desktop";
  } catch (error) {
    announcer.textContent = error.message;
  }
});

releaseControl.addEventListener("click", async () => {
  try {
    const state = await api("/api/v1/control/human/release", {
      method: "POST",
      human: true,
      body: JSON.stringify({ sessionId }),
    });
    renderLease(state);
    announcer.textContent = "Control returned to the AI operator";
  } catch (error) {
    announcer.textContent = error.message;
  }
});

openTools.addEventListener("click", () => {
  drawer.hidden = !drawer.hidden;
  openTools.setAttribute("aria-expanded", String(!drawer.hidden));
  if (!drawer.hidden) {
    agentDrawer.hidden = true;
    openAgent.setAttribute("aria-expanded", "false");
    closeTools.focus();
  }
});

closeTools.addEventListener("click", () => {
  drawer.hidden = true;
  openTools.setAttribute("aria-expanded", "false");
  openTools.focus();
});

function toggleAgent(open) {
  agentDrawer.hidden = !open;
  openAgent.setAttribute("aria-expanded", String(open));
  if (open) {
    drawer.hidden = true;
    openTools.setAttribute("aria-expanded", "false");
    agentPrompt.focus();
  } else {
    openAgent.focus();
  }
}

openAgent.addEventListener("click", () => toggleAgent(agentDrawer.hidden));
closeAgent.addEventListener("click", () => toggleAgent(false));

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !drawer.hidden) {
    drawer.hidden = true;
    openTools.setAttribute("aria-expanded", "false");
    openTools.focus();
  } else if (event.key === "Escape" && !agentDrawer.hidden) {
    toggleAgent(false);
  }
});

document.querySelector("#fullscreen").addEventListener("click", async () => {
  if (!document.fullscreenElement) await document.querySelector("#relay-stage").requestFullscreen();
  else await document.exitFullscreen();
});

document.querySelector("#reconnect").addEventListener("click", connect);

installKind.addEventListener("change", () => {
  const isDeb = installKind.value === "deb";
  installValueLabel.textContent = isDeb ? "Path under Downloads" : "Package names";
  installValue.placeholder = isDeb ? "/home/desktop/Downloads/demo.deb" : "firefox-esr jq";
});

approvalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const kind = installKind.value;
  const plan = kind === "apt"
    ? { kind, packages: installValue.value.trim().split(/\s+/) }
    : { kind, path: installValue.value.trim() };
  approvalOutput.textContent = "Creating two-minute approval…";
  try {
    const result = await api("/api/v1/approvals", {
      method: "POST",
      human: true,
      body: JSON.stringify({ plan }),
    });
    approvalOutput.textContent = `Approval ${result.approvalId} · expires in ${result.expiresInSeconds}s`;
  } catch (error) {
    approvalOutput.textContent = error.message;
  }
});

function setAgentStatus(label, state = "ready") {
  agentStatus.dataset.state = state;
  agentStatusLabel.textContent = label;
}

function conciseError(error) {
  const raw = error instanceof Error ? error.message : String(error || "Agent request failed");
  if (/\b401 Unauthorized\b/i.test(raw)) {
    return "Provider authentication failed (401). Check OPENAI_API_KEY.";
  }
  if (/\b429 (Too Many Requests|Unauthorized)\b/i.test(raw)) {
    return "Provider rate limit or quota reached (429).";
  }
  const firstLine = raw.split(/\r?\n/, 1)[0].trim();
  return firstLine.length > 180 ? `${firstLine.slice(0, 177)}…` : firstLine;
}

function appendAgentMessage(role, text, label) {
  agentEmpty?.remove();
  const item = document.createElement("article");
  item.className = "agent-message";
  item.dataset.role = role;
  const itemLabel = document.createElement("p");
  itemLabel.className = "agent-message-label";
  itemLabel.textContent = label || role;
  const body = document.createElement("p");
  body.className = "agent-message-body";
  body.textContent = text;
  item.append(itemLabel, body);
  agentTranscript.append(item);
  while (agentTranscript.querySelectorAll(".agent-message").length > MAX_TRANSCRIPT_ITEMS) {
    agentTranscript.querySelector(".agent-message")?.remove();
  }
  agentTranscript.scrollTop = agentTranscript.scrollHeight;
  return body;
}

async function agentFetch(path, options = {}) {
  if (!humanToken) throw new Error("Connect to the desktop before using Coddy");
  return fetch(`/agent-api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Human-Control-Token": humanToken,
      "X-Coddy-Session-ID": agentSessionId,
      ...(options.headers || {}),
    },
  });
}

async function refreshAgentHealth() {
  if (!humanToken) return;
  try {
    const response = await agentFetch("/v1/models", { method: "GET" });
    if (!response.ok) throw new Error(`Coddy status failed (${response.status})`);
    const models = await response.json();
    const available = Array.isArray(models.data) ? models.data.length : 0;
    const modelName = available && typeof models.data[0]?.id === "string"
      ? models.data[0].id
      : "";
    setAgentStatus(modelName ? `Agent online · ${modelName}` : "Agent online · configure a model");
  } catch (error) {
    setAgentStatus(conciseError(error), "error");
  }
}

async function loadAgentHistory() {
  if (agentHistoryLoaded || !humanToken) return;
  try {
    const response = await agentFetch(`/coddy/sessions/${agentSessionId}/messages`, { method: "GET" });
    if (response.status === 404) {
      agentHistoryLoaded = true;
      return;
    }
    if (!response.ok) throw new Error(`Conversation restore failed (${response.status})`);
    const history = await response.json();
    const messages = Array.isArray(history.messages) ? history.messages.slice(-50) : [];
    for (const message of messages) {
      if (!message || typeof message.content !== "string") continue;
      const role = message.role === "user" ? "user" : "assistant";
      appendAgentMessage(role, message.content.slice(0, 4000), role === "user" ? "Your outcome" : "Coddy");
    }
    agentHistoryLoaded = true;
  } catch (error) {
    setAgentStatus(conciseError(error), "error");
  }
}

function showPermission(payload) {
  if (pendingPermission) {
    if (permissionQueue.length >= 20) throw new Error("Too many pending permission requests");
    permissionQueue.push(payload);
    return;
  }
  const toolCall = payload.toolCall || payload.tool_call || {};
  pendingPermission = {
    toolCallId: toolCall.toolCallId || toolCall.tool_call_id || payload.toolCallId,
  };
  permissionTitle.textContent = toolCall.title || "Coddy wants to run a protected action";
  permissionDetail.textContent = JSON.stringify(toolCall.content || toolCall, null, 2).slice(0, 2000);
  permissionCard.hidden = false;
  permissionAllow.focus();
}

async function resolvePermission(optionId) {
  if (!pendingPermission?.toolCallId) return;
  let resolved = false;
  permissionAllow.disabled = true;
  permissionReject.disabled = true;
  try {
    const response = await agentFetch(`/coddy/sessions/${agentSessionId}/permission`, {
      method: "POST",
      body: JSON.stringify({ toolCallId: pendingPermission.toolCallId, optionId }),
    });
    if (!response.ok) throw new Error(`Permission update failed (${response.status})`);
    appendAgentMessage("tool", optionId === "allow" ? "Protected action allowed once." : "Protected action rejected.", "Human decision");
    permissionCard.hidden = true;
    pendingPermission = null;
    resolved = true;
  } catch (error) {
    setAgentStatus(conciseError(error), "error");
  } finally {
    permissionAllow.disabled = false;
    permissionReject.disabled = false;
  }
  if (resolved && permissionQueue.length) showPermission(permissionQueue.shift());
}

permissionAllow.addEventListener("click", () => resolvePermission("allow"));
permissionReject.addEventListener("click", () => resolvePermission("reject"));

function handleAgentEvent(name, data, assistantBody) {
  if (data === "[DONE]") return true;
  let payload;
  try { payload = JSON.parse(data); } catch { throw new Error("Agent sent malformed stream data"); }
  if (payload.error) {
    const message = typeof payload.error === "string" ? payload.error : payload.error.message;
    throw new Error(message || "Agent stream failed");
  }
  if (name === "permission") {
    showPermission(payload);
    setAgentStatus("Waiting for your confirmation", "working");
    return false;
  }
  if (name === "tool_call" || name === "tool_call_update") {
    const tool = payload.toolCall || payload.tool_call || payload;
    const title = tool.title || tool.name || "Desktop tool";
    const status = tool.status ? ` · ${tool.status}` : "";
    appendAgentMessage("tool", `${title}${status}`, "Agent action");
    setAgentStatus("Operating the desktop", "working");
    return false;
  }
  if (name === "error") throw new Error(payload.message || "Agent stream failed");
  const delta = payload.choices?.[0]?.delta?.content;
  if (typeof delta === "string") {
    if (assistantBody.textContent.length + delta.length > MAX_ASSISTANT_CHARS) {
      throw new Error("Agent text exceeded the 256 KiB display limit");
    }
    assistantBody.textContent += delta;
    agentTranscript.scrollTop = agentTranscript.scrollHeight;
  }
  return false;
}

async function consumeAgentStream(response, assistantBody) {
  if (!response.body) throw new Error("Agent returned no stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines = [];
  let totalBytes = 0;
  let receivedDone = false;
  const dispatch = () => {
    if (dataLines.length) {
      const data = dataLines.join("\n");
      if (data.length > MAX_EVENT_CHARS) throw new Error("Agent event exceeded 256 KiB");
      receivedDone ||= handleAgentEvent(eventName, data, assistantBody);
    }
    eventName = "message";
    dataLines = [];
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      totalBytes += value?.byteLength || 0;
      if (totalBytes > MAX_STREAM_BYTES) throw new Error("Agent stream exceeded 8 MiB");
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      if (buffer.length > MAX_EVENT_CHARS) throw new Error("Agent stream line exceeded 256 KiB");
      const lines = buffer.split(/\r?\n/);
      buffer = done ? "" : lines.pop();
      for (const line of lines) {
        if (line === "") dispatch();
        else if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) {
          let data = line.slice(5);
          if (data.startsWith(" ")) data = data.slice(1);
          dataLines.push(data);
        }
      }
      if (done) {
        dispatch();
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => null);
    reader.releaseLock();
  }
  if (!receivedDone) throw new Error("Agent stream ended before completion");
}

async function releaseHumanForAgent() {
  if (document.body.dataset.owner !== "human-self") return;
  const state = await api("/api/v1/control/human/release", {
    method: "POST",
    human: true,
    body: JSON.stringify({ sessionId }),
  });
  renderLease(state);
}

async function runAgent(prompt) {
  await releaseHumanForAgent();
  appendAgentMessage("user", prompt, "Your outcome");
  const assistantBody = appendAgentMessage("assistant", "", "Coddy");
  agentAbort = new AbortController();
  agentSend.disabled = true;
  agentStop.hidden = false;
  setAgentStatus("Inspecting the desktop", "working");
  try {
    const response = await agentFetch("/v1/responses", {
      method: "POST",
      body: JSON.stringify({ model: "agent", input: prompt, stream: true }),
      signal: agentAbort.signal,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error?.message || `Agent request failed (${response.status})`);
    }
    await consumeAgentStream(response, assistantBody);
    if (!assistantBody.textContent) assistantBody.textContent = "Task turn completed without a text reply.";
    setAgentStatus("Ready for the next outcome");
  } catch (error) {
    if (error.name === "AbortError") setAgentStatus("Agent stopped");
    else {
      assistantBody.textContent ||= conciseError(error);
      setAgentStatus(conciseError(error), "error");
    }
  } finally {
    agentAbort = null;
    agentSend.disabled = false;
    agentStop.hidden = true;
  }
}

agentForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = agentPrompt.value.trim();
  if (!prompt || agentAbort) return;
  agentPrompt.value = "";
  runAgent(prompt);
});

agentPrompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    agentForm.requestSubmit();
  }
});

agentStop.addEventListener("click", async () => {
  agentAbort?.abort();
  await agentFetch(`/coddy/sessions/${agentSessionId}/cancel`, {
    method: "POST",
    body: "{}",
  }).catch(() => null);
});

setInterval(async () => {
  const current = await api("/api/v1/control", { method: "GET", headers: {} }).catch(() => null);
  if (!current) return;
  if (current.owner === "human" && current.ownerId === sessionId) {
    const renewed = await api("/api/v1/control/human/heartbeat", {
      method: "POST",
      human: true,
      body: JSON.stringify({ sessionId }),
    }).catch(() => current);
    renderLease(renewed);
  } else {
    renderLease(current);
  }
}, 5000);

connect();
refreshLease();
