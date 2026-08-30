import RFB from "/novnc/core/rfb.js";
import {
  applyAgentEvent,
  normalizeHistory,
  renderMarkdown,
} from "/agent-view.mjs";
import {
  CAMERA_EASING,
  CAMERA_IDLE_TIMEOUT_MS,
  CAMERA_TRANSITION_MS,
  SHOWCASE_ACTIVE_ZOOM,
  SHOWCASE_IDLE_ZOOM,
  normalizeZoom,
  pointerOrigin,
} from "/zoom.mjs";

const screen = document.querySelector("#desktop-screen");
const desktopViewport = document.querySelector("#desktop-viewport");
const placeholder = document.querySelector("#feed-placeholder");
const leaseOwner = document.querySelector("#lease-owner");
const leaseDetail = document.querySelector("#lease-detail");
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
const openAgent = document.querySelector("#open-agent");
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
const displayMeta = document.querySelector("#display-meta");
const sidebarReopen = document.querySelector("#sidebar-reopen");
const feedPlaceholderLabel = document.querySelector("#feed-placeholder-label");
const feedPlaceholderSub = document.querySelector("#feed-placeholder-sub");
const openShortcuts = document.querySelector("#open-shortcuts");
const shortcutsDialog = document.querySelector("#shortcuts-dialog");
const fullscreenLabel = document.querySelector("#fullscreen-label");
const newAgentSession = document.querySelector("#new-agent-session");
const collapseAgent = document.querySelector("#collapse-agent");
const recordingToggle = document.querySelector("#recording-toggle");
const recordingLabel = document.querySelector("#recording-label");
const discardRecording = document.querySelector("#discard-recording");
const activityLog = document.querySelector("#activity-log");
const sessionId = crypto.randomUUID();
const storedAgentSession = localStorage.getItem("relay.coddy.session");
let agentSessionId = /^sess_[0-9a-f]{16,64}$/.test(storedAgentSession || "")
  ? storedAgentSession
  : `sess_${crypto.randomUUID().replaceAll("-", "")}`;
localStorage.setItem("relay.coddy.session", agentSessionId);
let rfb;
let selkiesFrame;
let streamingBackend = "vnc";
let reconnectTimer;
let humanToken = "";
let agentAbort;
let pendingPermission;
let agentHistoryLoaded = false;
let transcriptItems = [];
const permissionQueue = [];
let desktopZoom = SHOWCASE_IDLE_ZOOM;
let desktopDisplay = { width: 1440, height: 900 };
const cameraAnimations = new WeakMap();
let cameraIdleTimer;

function modKey(event) {
  return event.metaKey || event.ctrlKey;
}

function isTypingContext(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

function updatePageTitle(owner) {
  const suffix = ({
    "human-self": "You have control",
    agent: "Agent operating",
    human: "Another viewer",
    none: "Observer",
  })[owner] || "Observer";
  document.title = `Cloud Agent · ${suffix}`;
}

function closeControlDrawer() {
  drawer.hidden = true;
  openTools.setAttribute("aria-expanded", "false");
}

function isAgentOpen() {
  return document.body.dataset.agentOpen !== "false";
}

function toggleAgent(open, { focus = true } = {}) {
  const next = Boolean(open);
  document.body.dataset.agentOpen = String(next);
  localStorage.setItem("relay.agent.panel", next ? "open" : "closed");
  openAgent.setAttribute("aria-expanded", String(next));
  collapseAgent.setAttribute("aria-expanded", String(next));
  if (sidebarReopen) sidebarReopen.hidden = next;
  if (!focus) return;
  if (next) agentPrompt.focus();
  else openAgent.focus();
}

function desktopSurfaces() {
  return [...desktopViewport.querySelectorAll("canvas, .selkies-frame")];
}

function prefersReducedCameraMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
}

function setCameraOrigin(pivot) {
  const origin = pointerOrigin(pivot, desktopDisplay, desktopZoom);
  const target = `${origin.x} ${origin.y}`;
  desktopViewport.style.setProperty("--desktop-zoom-origin-x", origin.x);
  desktopViewport.style.setProperty("--desktop-zoom-origin-y", origin.y);

  for (const surface of desktopSurfaces()) {
    const current = getComputedStyle(surface).transformOrigin;
    cameraAnimations.get(surface)?.cancel();
    surface.style.transformOrigin = target;
    if (prefersReducedCameraMotion() || typeof surface.animate !== "function") continue;
    const animation = surface.animate(
      [{ transformOrigin: current }, { transformOrigin: target }],
      { duration: CAMERA_TRANSITION_MS, easing: CAMERA_EASING },
    );
    cameraAnimations.set(surface, animation);
  }
}

function setDesktopZoom(
  value,
  { pivot = null, announce = true, instantZoom = false } = {},
) {
  desktopZoom = normalizeZoom(value);
  if (pivot) setCameraOrigin(pivot);

  const surfaces = desktopSurfaces();
  if (instantZoom) {
    for (const surface of surfaces) {
      cameraAnimations.get(surface)?.cancel();
      surface.style.transition = "none";
    }
  }
  desktopViewport.style.setProperty("--desktop-zoom", String(desktopZoom));
  if (instantZoom) {
    for (const surface of surfaces) getComputedStyle(surface).transform;
    for (const surface of surfaces) surface.style.removeProperty("transition");
  }
  const level = `${Math.round(desktopZoom * 100)}%`;
  if (announce) announcer.textContent = `Desktop zoom ${level}`;
}

function scheduleCameraIdle() {
  clearTimeout(cameraIdleTimer);
  cameraIdleTimer = setTimeout(() => {
    if (document.body.dataset.owner !== "human-self") {
      setDesktopZoom(SHOWCASE_IDLE_ZOOM, { announce: false });
    }
  }, CAMERA_IDLE_TIMEOUT_MS);
}

setDesktopZoom(desktopZoom, { announce: false });

function websocketUrl() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/websockify`;
}

async function detectStreamingBackend() {
  try {
    const health = await fetch("/api/v1/health", { cache: "no-store" }).then((response) => response.json());
    streamingBackend = health?.streaming?.backend === "selkies" ? "selkies" : "vnc";
    return health;
  } catch {
    streamingBackend = "vnc";
    return null;
  }
}

function disconnectStream() {
  if (rfb) {
    try { rfb.disconnect(); } catch { /* The transport is already gone. */ }
    rfb = undefined;
  }
  if (selkiesFrame) {
    selkiesFrame.remove();
    selkiesFrame = undefined;
  }
}

function connectSelkies(path = "/selkies/") {
  disconnectStream();
  setFeedStatus("Connecting to desktop", "Opening Selkies stream");
  selkiesFrame = document.createElement("iframe");
  selkiesFrame.src = path;
  selkiesFrame.title = "Remote Linux desktop";
  selkiesFrame.className = "selkies-frame";
  selkiesFrame.allow = "autoplay; clipboard-read; clipboard-write; fullscreen";
  selkiesFrame.addEventListener("load", () => {
    placeholder?.remove();
    announcer.textContent = "Remote desktop connected";
  }, { once: true });
  desktopViewport.appendChild(selkiesFrame);
}

function connectVnc() {
  disconnectStream();
  setFeedStatus("Connecting to desktop", "Opening WebSocket to VNC bridge");
  rfb = new RFB(desktopViewport, websocketUrl(), { shared: true });
  rfb.scaleViewport = true;
  rfb.resizeSession = false;
  rfb.viewOnly = true;
  rfb.qualityLevel = 7;
  rfb.compressionLevel = 3;

  rfb.addEventListener("connect", () => {
    placeholder?.remove();
    announcer.textContent = "Remote desktop connected";
  });
  rfb.addEventListener("credentialsrequired", () => {
    setFeedStatus("Authenticating", "Enter the VNC password to continue");
    if (!credentialsDialog.open) credentialsDialog.showModal();
    passwordInput.focus();
  });
  rfb.addEventListener("securityfailure", () => {
    humanToken = "";
    passwordInput.value = "";
    passwordInput.setAttribute("aria-invalid", "true");
    announcer.textContent = "VNC password rejected";
    if (!credentialsDialog.open) credentialsDialog.showModal();
  });
  rfb.addEventListener("disconnect", (event) => {
    announcer.textContent = event.detail.clean ? "Remote desktop disconnected" : "Remote desktop connection lost";
    if (!event.detail.clean) reconnectTimer = setTimeout(connect, 2000);
  });
}

async function connect() {
  clearTimeout(reconnectTimer);
  await detectStreamingBackend();
  if (streamingBackend === "selkies") {
    if (!humanToken) {
      setFeedStatus("Authenticating", "Enter the VNC password to continue");
      if (!credentialsDialog.open) credentialsDialog.showModal();
      passwordInput.focus();
      return;
    }
    connectSelkies();
    return;
  }
  connectVnc();
}

function setFeedStatus(label, sub = "") {
  if (feedPlaceholderLabel) feedPlaceholderLabel.textContent = label;
  if (feedPlaceholderSub) feedPlaceholderSub.textContent = sub;
}

credentialsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const password = passwordInput.value;
  if (!password) return;
  humanToken = password;
  passwordInput.removeAttribute("aria-invalid");
  passwordInput.value = "";
  credentialsDialog.close();
  if (streamingBackend === "selkies") {
    connectSelkies();
  } else if (rfb) {
    rfb.sendCredentials({ password });
  } else {
    connect();
  }
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
  const owner = isOurs ? "human-self" : state.owner;
  document.body.dataset.owner = owner;
  takeControl.disabled = isOurs;
  releaseControl.disabled = !isOurs;
  takeControl.setAttribute("aria-pressed", String(isOurs));
  releaseControl.setAttribute("aria-pressed", String(isOurs));
  if (rfb) rfb.viewOnly = !isOurs;
  updatePageTitle(owner);

  if (isOurs) {
    leaseOwner.textContent = "You";
    leaseDetail.textContent = leaseDetailText("Keyboard and pointer are live");
  } else if (state.owner === "agent") {
    leaseOwner.textContent = "AI operator";
    leaseDetail.textContent = leaseDetailText("Watching the agent work");
  } else if (state.owner === "human") {
    leaseOwner.textContent = "Another viewer";
    leaseDetail.textContent = leaseDetailText("This feed is view-only");
  } else {
    leaseOwner.textContent = "Observer";
    leaseDetail.textContent = leaseDetailText("No input is being sent");
  }
}

async function refreshDesktopHealth() {
  try {
    const health = await api("/api/v1/health", { method: "GET", headers: {} });
    const width = health?.display?.width;
    const height = health?.display?.height;
    if (displayMeta && width && height) {
      displayMeta.textContent = `${width}×${height} framebuffer`;
    }
    if (width && height) desktopDisplay = { width, height };
    if (health?.recording) syncRecordingControls(health.recording);
    if (health?.showcase && document.body.dataset.owner !== "human-self") {
      setDesktopZoom(health.showcase.zoom, {
        pivot: health.showcase.pivot,
        announce: false,
      });
      if (health.showcase.zoom >= SHOWCASE_ACTIVE_ZOOM) scheduleCameraIdle();
      else clearTimeout(cameraIdleTimer);
    }
  } catch {
    if (displayMeta) displayMeta.textContent = "Framebuffer unknown";
  }
}

function syncRecordingControls(recording = {}) {
  if (!recordingToggle) return;
  const active = Boolean(recording.active);
  recordingToggle.dataset.active = String(active);
  recordingToggle.setAttribute("aria-pressed", String(active));
  recordingToggle.setAttribute("aria-label", active ? "Stop and save recording" : "Start screen recording");
  recordingToggle.title = active ? "Stop and save recording" : "Start screen recording";
  if (recordingLabel) recordingLabel.textContent = active ? "Stop" : "Record";
  if (discardRecording) discardRecording.hidden = !active;
}

async function refreshLease() {
  try {
    renderLease(await api("/api/v1/control", { method: "GET", headers: {} }));
  } catch (error) {
    leaseDetail.textContent = error.message;
  }
}

takeControl.addEventListener("click", async () => {
  takeControl.dataset.loading = "true";
  try {
    const state = await api("/api/v1/control/human/claim", {
      method: "POST",
      human: true,
      body: JSON.stringify({ sessionId }),
    });
    renderLease(state);
    // Showcase zoom belongs to the AI observer. Return the visual surface to
    // 1:1 before human input reaches noVNC, whose coordinates are unzoomed.
    setDesktopZoom(1, { announce: false, instantZoom: true });
    screen.focus();
    announcer.textContent = "You now control the remote desktop";
  } catch (error) {
    announcer.textContent = error.message;
  } finally {
    takeControl.dataset.loading = "false";
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
    refreshDesktopHealth();
    announcer.textContent = "Control returned to observer mode";
  } catch (error) {
    announcer.textContent = error.message;
  }
});

openTools.addEventListener("click", () => {
  const open = drawer.hidden;
  closeControlDrawer();
  drawer.hidden = !open;
  openTools.setAttribute("aria-expanded", String(open));
  if (open) {
    closeTools.focus();
  }
});

closeTools.addEventListener("click", () => {
  closeControlDrawer();
  openTools.focus();
});

openAgent.addEventListener("click", () => toggleAgent(!isAgentOpen()));
collapseAgent.addEventListener("click", () => toggleAgent(false));
openShortcuts?.addEventListener("click", () => shortcutsDialog?.showModal());

async function claimHumanControl() {
  if (document.body.dataset.owner === "human-self") return;
  takeControl.click();
}

async function releaseHumanControl() {
  if (document.body.dataset.owner !== "human-self") return;
  releaseControl.click();
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!drawer.hidden) {
      closeControlDrawer();
      openTools.focus();
      return;
    }
    if (shortcutsDialog?.open) {
      shortcutsDialog.close();
      return;
    }
  }
  if (isTypingContext(event.target)) return;
  if (event.key === "?" && !modKey(event)) {
    event.preventDefault();
    shortcutsDialog?.showModal();
    return;
  }
  if (modKey(event) && event.key === ".") {
    event.preventDefault();
    toggleAgent(!isAgentOpen());
    return;
  }
  if (modKey(event) && event.key === ",") {
    event.preventDefault();
    openTools.click();
    return;
  }
  if (modKey(event) && event.shiftKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    document.querySelector("#fullscreen")?.click();
    return;
  }
  if (modKey(event) && event.shiftKey && event.key === "Enter") {
    event.preventDefault();
    releaseHumanControl();
    return;
  }
  if (modKey(event) && event.key === "Enter") {
    event.preventDefault();
    claimHumanControl();
    return;
  }
  if (!modKey(event) && !event.altKey && event.key.toLowerCase() === "t") {
    event.preventDefault();
    claimHumanControl();
    return;
  }
  if (!modKey(event) && !event.altKey && event.key.toLowerCase() === "r") {
    event.preventDefault();
    releaseHumanControl();
  }
});

document.addEventListener("fullscreenchange", () => {
  if (fullscreenLabel) {
    fullscreenLabel.textContent = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen";
  }
});

document.querySelector("#fullscreen").addEventListener("click", async () => {
  if (!document.fullscreenElement) await document.querySelector("#relay-stage").requestFullscreen();
  else await document.exitFullscreen();
});

function resetAgentConversation() {
  agentSessionId = `sess_${crypto.randomUUID().replaceAll("-", "")}`;
  localStorage.setItem("relay.coddy.session", agentSessionId);
  agentHistoryLoaded = false;
  transcriptItems = [];
  agentTranscript.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "agent-empty";
  empty.id = "agent-empty";
  empty.innerHTML = '<span class="agent-empty-mark" aria-hidden="true">↳</span><p>Tell Coddy what should be true on the desktop. It will inspect, act, and verify in the same session you can take over.</p>';
  agentTranscript.append(empty);
  permissionCard.hidden = true;
  pendingPermission = null;
  permissionQueue.length = 0;
  setAgentStatus("Ready for a new conversation");
  announcer.textContent = "Started a new Coddy conversation";
}

newAgentSession?.addEventListener("click", () => {
  if (!window.confirm("Start a new Coddy conversation? The current transcript will clear in this browser.")) return;
  resetAgentConversation();
});

let eventSource;

function applyShowcaseCameraEvent(event) {
  if (event.kind !== "showcase.camera") return;
  if (document.body.dataset.owner === "human-self") return;
  const detail = event.detail || {};
  const width = detail.display?.width;
  const height = detail.display?.height;
  if (width && height) desktopDisplay = { width, height };
  setDesktopZoom(detail.zoom, { pivot: detail.pivot, announce: false });
  if (detail.zoom >= SHOWCASE_ACTIVE_ZOOM) scheduleCameraIdle();
  else clearTimeout(cameraIdleTimer);
}

function appendActivityLine(event) {
  if (!activityLog || ["heartbeat", "showcase.camera"].includes(event.kind)) return;
  const line = `[${event.kind}] ${event.title}`;
  activityLog.textContent = `${activityLog.textContent}${line}\n`.slice(-4000);
}

function connectActivityStream() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/api/v1/events/stream");
  eventSource.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data);
      applyShowcaseCameraEvent(event);
      appendActivityLine(event);
    } catch {
      /* ignore malformed stream payloads */
    }
  };
}

async function recordingAction(path, active) {
  if (!recordingToggle) return;
  recordingToggle.disabled = true;
  if (discardRecording) discardRecording.disabled = true;
  try {
    const result = await api(path, { method: "POST", human: true, body: "{}" });
    syncRecordingControls({ active });
    announcer.textContent = result?.path
      ? `Recording saved to ${result.path}`
      : `Recording ${result?.status || "updated"}`;
    await refreshDesktopHealth();
  } catch (error) {
    announcer.textContent = error.message;
  } finally {
    recordingToggle.disabled = false;
    if (discardRecording) discardRecording.disabled = false;
  }
}

recordingToggle?.addEventListener("click", () => {
  const active = recordingToggle.dataset.active === "true";
  recordingAction(active ? "/api/v1/recording/stop" : "/api/v1/recording/start", !active);
});
discardRecording?.addEventListener("click", () => recordingAction("/api/v1/recording/discard", false));

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

function leaseDetailText(base) {
  return base;
}

function messageLabel(role) {
  return ({
    user: "Your outcome",
    assistant: "Coddy",
    reasoning: "Thinking",
    error: "Turn stopped",
    decision: "Human decision",
  })[role] || "Coddy";
}

function statusLabel(status) {
  return ({
    pending: "Queued",
    in_progress: "Running",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Cancelled",
  })[status] || status || "Queued";
}

function toolDetails(item) {
  const sections = [];
  if (item.rawInput) sections.push(`Input\n${typeof item.rawInput === "string" ? item.rawInput : JSON.stringify(item.rawInput, null, 2)}`);
  if (item.detail) sections.push(`Result\n${item.detail}`);
  return sections.join("\n\n").slice(0, 4_000);
}

function renderTranscript() {
  agentEmpty?.remove();
  agentTranscript.replaceChildren();
  for (const entry of transcriptItems) {
    if (entry.type === "tool") {
      const item = document.createElement("article");
      item.className = "agent-message agent-tool";
      item.dataset.role = "tool";
      item.dataset.status = entry.status;
      const label = document.createElement("p");
      label.className = "agent-message-label";
      label.textContent = "Agent action";
      const heading = document.createElement("div");
      heading.className = "agent-tool-heading";
      const title = document.createElement("strong");
      title.textContent = entry.title;
      const status = document.createElement("span");
      status.className = "agent-tool-status";
      status.textContent = statusLabel(entry.status);
      heading.append(title, status);
      item.append(label, heading);
      const detail = toolDetails(entry);
      if (detail) {
        const disclosure = document.createElement("details");
        disclosure.open = entry.status === "failed";
        const summary = document.createElement("summary");
        summary.textContent = entry.status === "failed" ? "Failure details" : "Details";
        const body = document.createElement("pre");
        body.textContent = detail;
        disclosure.append(summary, body);
        item.append(disclosure);
      }
      agentTranscript.append(item);
      continue;
    }
    const item = document.createElement("article");
    item.className = "agent-message";
    item.dataset.role = entry.role;
    if (entry.streaming) item.classList.add("agent-message-streaming");
    const label = document.createElement("p");
    label.className = "agent-message-label";
    label.textContent = messageLabel(entry.role);
    const body = document.createElement("div");
    body.className = "agent-message-body agent-markdown";
    renderMarkdown(body, entry.content);
    item.append(label, body);
    agentTranscript.append(item);
  }
  agentTranscript.scrollTop = agentTranscript.scrollHeight;
}

function appendAgentMessage(role, text) {
  if (!String(text || "").trim()) return;
  transcriptItems.push({ type: "message", role, content: text, streaming: false });
  transcriptItems = transcriptItems.slice(-MAX_TRANSCRIPT_ITEMS);
  renderTranscript();
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
  setAgentStatus("Restoring conversation…", "working");
  agentTranscript.setAttribute("aria-busy", "true");
  try {
    const response = await agentFetch(`/coddy/sessions/${agentSessionId}/messages`, { method: "GET" });
    if (response.status === 404) {
      agentHistoryLoaded = true;
      return;
    }
    if (!response.ok) throw new Error(`Conversation restore failed (${response.status})`);
    const history = await response.json();
    transcriptItems = normalizeHistory(history.messages).slice(-MAX_TRANSCRIPT_ITEMS);
    if (transcriptItems.length) {
      renderTranscript();
    }
    agentHistoryLoaded = true;
  } catch (error) {
    setAgentStatus(conciseError(error), "error");
  } finally {
    agentTranscript.removeAttribute("aria-busy");
  }
}

function showPermission(payload) {
  toggleAgent(true);
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
    appendAgentMessage("decision", optionId === "allow" ? "Protected action allowed once." : "Protected action rejected.");
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

function handleAgentEvent(name, data) {
  if (data === "[DONE]") {
    transcriptItems = applyAgentEvent(transcriptItems, name, data);
    renderTranscript();
    return true;
  }
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
    setAgentStatus(tool.status === "failed" ? "An action failed · Coddy is reviewing" : "Operating the desktop", "working");
  }
  if (name === "error") throw new Error(payload.message || "Agent stream failed");
  const next = applyAgentEvent(transcriptItems, name, payload);
  if (next.some((item) => item.type === "message" && item.content.length > MAX_ASSISTANT_CHARS)) {
    throw new Error("Agent text exceeded the 256 KiB display limit");
  }
  transcriptItems = next.slice(-MAX_TRANSCRIPT_ITEMS);
  renderTranscript();
  return false;
}

async function consumeAgentStream(response) {
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
      receivedDone ||= handleAgentEvent(eventName, data);
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
  appendAgentMessage("user", prompt);
  const turnStartIndex = transcriptItems.length;
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
    await consumeAgentStream(response);
    const turnItems = transcriptItems.slice(turnStartIndex);
    if (!turnItems.length) appendAgentMessage("assistant", "Task turn completed without a text reply.");
    const failed = turnItems.some((item) => item.type === "tool" && item.status === "failed");
    setAgentStatus(failed ? "Turn ended after a failed action" : "Ready for the next outcome", failed ? "error" : "ready");
  } catch (error) {
    if (error.name === "AbortError") setAgentStatus("Agent stopped");
    else {
      const message = conciseError(error);
      appendAgentMessage("error", message);
      setAgentStatus(message, "error");
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
connectActivityStream();
refreshLease();
refreshDesktopHealth();
updatePageTitle("none");
toggleAgent(localStorage.getItem("relay.agent.panel") !== "closed", { focus: false });
