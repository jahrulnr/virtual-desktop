const START_PAGE = "http://127.0.0.1:8080/start-page/index.html";
const RELAY_SHELL_ORIGIN = "http://127.0.0.1:8080";

// Chromium can restore the old Relay shell tab from a persistent profile before
// the startup preference takes effect. Normalize that initial browser state once,
// while leaving every tab opened later by the agent or human untouched. The
// guard is per browser context because the MCP server can create a new browser
// after an earlier context was closed.
const preparedContexts = new WeakSet();

function isRelayPage(url: string, pathname: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.origin === RELAY_SHELL_ORIGIN && parsed.pathname === pathname;
  } catch {
    return false;
  }
}

function isStartPage(url: string): boolean {
  return isRelayPage(url, "/start-page/index.html");
}

function isBootPage(url: string): boolean {
  return url === "about:blank" || url === "chrome://newtab/" || isRelayPage(url, "/");
}

export default async ({ page }) => {
  const context = page.context();
  if (preparedContexts.has(context)) {
    return;
  }

  preparedContexts.add(context);
  const pages = context.pages();
  const startPage = pages.find((candidate) => isStartPage(candidate.url()));
  const bootPage = pages.find((candidate) => isBootPage(candidate.url()));
  const targetPage = startPage ?? bootPage;

  // If Chromium restored only real work tabs, do not hijack one of them.
  if (!targetPage) {
    return;
  }

  await Promise.all(
    pages
      .filter((candidate) => candidate !== targetPage && isBootPage(candidate.url()))
      .map((candidate) => candidate.close().catch(() => undefined)),
  );

  if (!isStartPage(targetPage.url())) {
    await targetPage.goto(START_PAGE, { waitUntil: "domcontentloaded" });
  }
  await targetPage.bringToFront();
};
