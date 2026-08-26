const BACKEND_PATHS = [
  "/api/",
  "/media/",
  "/health",
  "/docs",
  "/redoc",
  "/openapi.json",
];

export function isBackendPath(pathname) {
  return BACKEND_PATHS.some((prefix) =>
    prefix.endsWith("/")
      ? pathname.startsWith(prefix)
      : pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function upstreamUrl(requestUrl, backendOrigin) {
  const incoming = new URL(requestUrl);
  const upstream = new URL(backendOrigin);
  upstream.pathname = incoming.pathname;
  upstream.search = incoming.search;
  return upstream;
}

async function proxyToBackend(request, env) {
  if (!env.BACKEND_ORIGIN) {
    return Response.json(
      { detail: "Worker backend origin is not configured" },
      { status: 503 },
    );
  }

  const incomingUrl = new URL(request.url);
  const target = upstreamUrl(request.url, env.BACKEND_ORIGIN);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("x-forwarded-host", incomingUrl.host);
  headers.set("x-forwarded-proto", incomingUrl.protocol.replace(":", ""));

  const upstreamRequest = new Request(target, {
    method: request.method,
    headers,
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
    redirect: "manual",
  });
  const response = await fetch(upstreamRequest);
  const responseHeaders = new Headers(response.headers);
  responseHeaders.set("x-ai-fashion-edge", "cloudflare-workers");
  if (incomingUrl.pathname.startsWith("/api/")) {
    responseHeaders.set("cache-control", "private, no-store");
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (isBackendPath(url.pathname)) {
      return proxyToBackend(request, env);
    }
    return env.ASSETS.fetch(request);
  },
};
