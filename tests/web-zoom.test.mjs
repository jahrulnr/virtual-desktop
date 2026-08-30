import assert from "node:assert/strict";
import test from "node:test";

import {
  CAMERA_EASING,
  CAMERA_IDLE_TIMEOUT_MS,
  CAMERA_TRANSITION_MS,
  SHOWCASE_ACTIVE_ZOOM,
  SHOWCASE_IDLE_ZOOM,
  normalizeZoom,
  pointerOrigin,
} from "../web/zoom.mjs";

test("the automatic showcase camera only exposes wide and fixed zoom views", () => {
  assert.equal(SHOWCASE_IDLE_ZOOM, 1);
  assert.equal(SHOWCASE_ACTIVE_ZOOM, 2);
  assert.equal(CAMERA_IDLE_TIMEOUT_MS, 1000);
  assert.equal(CAMERA_TRANSITION_MS, 240);
  assert.equal(CAMERA_EASING, "cubic-bezier(.3333, 1, .6667, 1)");
  assert.equal(normalizeZoom(0.1), 1);
  assert.equal(normalizeZoom(2), 2);
  assert.equal(normalizeZoom(9), 2);
  assert.equal(normalizeZoom("bad"), 1);
});

test("showcase zoom derives its transform origin from the real framebuffer pointer", () => {
  assert.deepEqual(pointerOrigin({ x: 360, y: 225 }, { width: 1440, height: 900 }), {
    x: "25%",
    y: "25%",
  });
  assert.deepEqual(pointerOrigin({ x: -50, y: 9999 }, { width: 1440, height: 900 }), {
    x: "0%",
    y: "100%",
  });
  assert.deepEqual(pointerOrigin(null, null), { x: "50%", y: "50%" });
});
