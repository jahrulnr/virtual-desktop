export const SHOWCASE_IDLE_ZOOM = 1;
export const SHOWCASE_ACTIVE_ZOOM = 2;
export const CAMERA_IDLE_TIMEOUT_MS = 1000;
export const CAMERA_TRANSITION_MS = 240;
export const CAMERA_EASING = "cubic-bezier(.3333, 1, .6667, 1)";

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

export function normalizeZoom(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return 1;
  return clamp(value, SHOWCASE_IDLE_ZOOM, SHOWCASE_ACTIVE_ZOOM);
}

export function pointerOrigin(pointer, display, zoom = SHOWCASE_IDLE_ZOOM) {
  const width = Number.isFinite(display?.width) && display.width > 0 ? display.width : 1440;
  const height = Number.isFinite(display?.height) && display.height > 0 ? display.height : 900;
  const scale = clamp(Number.isFinite(zoom) ? zoom : SHOWCASE_IDLE_ZOOM, 1, SHOWCASE_ACTIVE_ZOOM);
  const rawX = Number.isFinite(pointer?.x) ? clamp(pointer.x, 0, width) : width / 2;
  const rawY = Number.isFinite(pointer?.y) ? clamp(pointer.y, 0, height) : height / 2;
  // Keep the transformed framebuffer fully inside its viewport. At 200%, an
  // origin outside the middle half would push an edge beyond the stage.
  const safeX = scale > 1 ? 0.5 / scale : 0;
  const safeY = scale > 1 ? 0.5 / scale : 0;
  const maxX = scale > 1 ? 1 - safeX : 1;
  const maxY = scale > 1 ? 1 - safeY : 1;
  const x = clamp(rawX / width, safeX, maxX);
  const y = clamp(rawY / height, safeY, maxY);
  return {
    x: `${Math.round(x * 10000) / 100}%`,
    y: `${Math.round(y * 10000) / 100}%`,
  };
}
