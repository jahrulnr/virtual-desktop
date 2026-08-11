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
const sessionId = crypto.randomUUID();
let rfb;
let reconnectTimer;
let hasConnected = false;
let humanToken = "";

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
  if (!drawer.hidden) closeTools.focus();
});

closeTools.addEventListener("click", () => {
  drawer.hidden = true;
  openTools.setAttribute("aria-expanded", "false");
  openTools.focus();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !drawer.hidden) {
    drawer.hidden = true;
    openTools.setAttribute("aria-expanded", "false");
    openTools.focus();
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
