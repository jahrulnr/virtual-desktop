import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const styles = await readFile(new URL("../web/styles.css", import.meta.url), "utf8");
const markup = await readFile(new URL("../web/index.html", import.meta.url), "utf8");
const app = await readFile(new URL("../web/app.js", import.meta.url), "utf8");

function ruleBody(selector) {
  const match = styles.match(new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `missing CSS rule ${selector}`);
  return match[1];
}

test("lease expiry warning is not rendered", () => {
  assert.doesNotMatch(markup, /lease-warning|renew-lease/);
  assert.doesNotMatch(styles, /lease-warning|renew-lease/);
});

test("session chrome lives in the sidebar while take-control stays centered", () => {
  const stage = markup.match(/<main\b[\s\S]*?<\/main>/)?.[0] || "";
  const sidebar = markup.match(/<aside\b[\s\S]*?class="agent-drawer"[\s\S]*?<\/aside>/)?.[0] || "";

  assert.match(stage, /class="control-pill take-control"/);
  assert.doesNotMatch(stage, /mode-banner|lease-card|showcase-zoom-status|control-drawer/);
  assert.match(markup, /class="sidebar-session"/);
  assert.match(markup, /class="lease-card"/);
  assert.match(markup, /class="sidebar-reopen"/);
  assert.match(sidebar, /id="control-drawer"/);
  assert.doesNotMatch(markup, /id="agent-canvas-badge"|id="operator-chip"/);
  assert.doesNotMatch(markup, /class="stage-status-stack"|class="stage-header"/);
  assert.match(ruleBody(".take-control"), /inset:\s*50% auto auto 50%/);
  assert.match(ruleBody(".take-control"), /transform:\s*translate\(-50%,\s*-50%\)/);
});

test("sidebar stays quiet and keeps only actionable session chrome", () => {
  assert.doesNotMatch(markup, /connection-chip|mode-banner|lease-countdown|showcase-zoom-status/);
  assert.doesNotMatch(styles, /\.connection-chip|\.mode-banner|\.sidebar-zoom-status/);
  assert.doesNotMatch(app, /connection-(dot|label|chip)|mode-banner|lease-countdown|showcaseZoomLevel|syncModeBanner|setConnection/);
  assert.match(ruleBody(".control-drawer"), /position:\s*static/);
  assert.match(ruleBody(".release-control"), /position:\s*static/);
  assert.match(ruleBody(".sidebar-reopen"), /display:\s*flex/);
  assert.match(styles, /@media\s*\(max-width:\s*860px\)[\s\S]*\.agent-drawer\s*\{[\s\S]*display:\s*flex/);
  assert.match(styles, /@media\s*\(max-width:\s*860px\)[\s\S]*overflow-y:\s*auto/);
  assert.doesNotMatch(ruleBody(".control-drawer"), /z-index\s*:/);
  assert.doesNotMatch(styles, /\.take-control\s*\{[^}]*bottom:/);
});

test("sidebar exposes matching collapse and expand controls", () => {
  assert.match(markup, /id="collapse-agent"[\s\S]*aria-controls="agent-drawer"[\s\S]*aria-expanded="true"[\s\S]*aria-label="Collapse sidebar"/);
  assert.match(markup, /id="open-agent"[\s\S]*aria-label="Expand sidebar"/);
  assert.doesNotMatch(markup, /id="close-agent"|Hide Coddy operator/);
  assert.match(app, /collapseAgent\.addEventListener\("click", \(\) => toggleAgent\(false\)\)/);
  assert.match(app, /collapseAgent\.setAttribute\("aria-expanded", String\(next\)\)/);
});

test("desktop controls use one recording switch and hide discard until recording starts", () => {
  assert.match(markup, /id="recording-toggle"[\s\S]*aria-pressed="false"/);
  assert.match(markup, /id="discard-recording"[^>]*hidden/);
  assert.doesNotMatch(markup, /id="start-recording"|id="stop-recording"|id="reconnect"|id="copy-session-id"|id="disconnect"/);
  assert.doesNotMatch(markup, /id="session-meta"/);
  assert.match(app, /recordingToggle\.dataset\.active/);
  assert.match(app, /recordingToggle\.setAttribute\("aria-pressed"/);
  assert.match(app, /\/api\/v1\/recording\/start/);
  assert.match(app, /\/api\/v1\/recording\/stop/);
  assert.match(app, /discardRecording\.hidden = !active/);
  assert.doesNotMatch(app, /copySessionId|disconnectButton|startRecording|stopRecording/);
  assert.match(styles, /\.tool-actions\s*\{[^}]*display:\s*grid/);
  assert.match(styles, /\.recording-switch\s*\{[^}]*justify-content:\s*flex-start/);
  assert.match(styles, /\.recording-switch\[data-active="true"\]/);
  assert.match(styles, /\.switch-track\s*\{[^}]*transition:/);
  assert.doesNotMatch(styles, /\.tool-grid\s*\{/);
});

test("showcase camera follows AI events without a user or agent zoom control", () => {
  assert.doesNotMatch(markup, /showcase-zoom-status|showcase-zoom-level/);
  assert.match(app, /setDesktopZoom/);
  assert.match(app, /event\.kind !== "showcase\.camera"/);
  assert.match(app, /document\.body\.dataset\.owner === "human-self"/);
  assert.match(app, /let desktopZoom = SHOWCASE_IDLE_ZOOM/);
  assert.match(app, /SHOWCASE_ACTIVE_ZOOM/);
  assert.match(app, /CAMERA_IDLE_TIMEOUT_MS/);
  assert.match(app, /surface\.animate\(/);
  assert.match(app, /CAMERA_TRANSITION_MS/);
  assert.match(app, /instantZoom: true/);
  assert.doesNotMatch(app, /showcase_zoom|event\.kind !== "showcase\.zoom"/);
  assert.doesNotMatch(markup, /id="zoom-(out|reset|in)"/);
  assert.match(styles, /\[hidden\]\s*\{[^}]*display:\s*none\s*!important/);
  assert.match(styles, /\.desktop-viewport canvas,[\s\S]*\.desktop-viewport \.selkies-frame\s*\{[^}]*transform:\s*scale\(var\(--desktop-zoom,\s*1\)\)/s);
  assert.match(styles, /transform-origin:\s*var\(--desktop-zoom-origin-x,\s*50%\)\s+var\(--desktop-zoom-origin-y,\s*50%\)/);
  assert.doesNotMatch(styles, /transform-origin\s+240ms/);
  assert.match(styles, /\.desktop-viewport canvas,[\s\S]*transition:\s*transform\s+240ms\s+cubic-bezier\(\.3333,\s*1,\s*\.6667,\s*1\)/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(app, /prefers-reduced-motion:\s*reduce/);
});

test("responsive scope targets tablet and desktop", () => {
  assert.match(styles, /@media\s*\(max-width:\s*860px\)/);
  assert.doesNotMatch(styles, /max-width:\s*620px/);
});
