import assert from "node:assert/strict";
import test from "node:test";

import { isBackendPath, upstreamUrl } from "./index.js";

test("backend routes are handled by the Worker", () => {
  for (const pathname of [
    "/api/v1/system/status",
    "/media/jobs/result.mp4",
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
  ]) {
    assert.equal(isBackendPath(pathname), true, pathname);
  }
});

test("frontend routes stay on the static asset binding", () => {
  for (const pathname of ["/", "/index.html", "/assets/app.js", "/workspace"]) {
    assert.equal(isBackendPath(pathname), false, pathname);
  }
});

test("upstream URL preserves path and query", () => {
  assert.equal(
    upstreamUrl(
      "https://aifactorycreator.org/api/v1/jobs?page=2&kind=video",
      "https://origin.aifactorycreator.org/base",
    ).toString(),
    "https://origin.aifactorycreator.org/api/v1/jobs?page=2&kind=video",
  );
});
