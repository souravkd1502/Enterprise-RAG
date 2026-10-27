/**
 * Small same-origin UI server using Node built-ins only.
 *
 * JWTs stay in process memory behind an opaque HttpOnly session cookie. A queue
 * serializes each session's refresh/select/logout operations to prevent backend
 * refresh-replay revocation. Restarting Node signs browser sessions out.
 */
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const messages = {
  400: "The request could not be completed.",
  401: "Your session expired or the sign-in details are incorrect. Please sign in.",
  403: "You do not have access to this workspace.",
  404: "Local authentication is unavailable. Check that the API uses AUTH_MODE=local.",
  409: "Account unavailable. If you already registered, try signing in.",
  422: "Check your email, name and password. Passwords need 15–128 characters.",
  429: "Too many requests. Please wait a minute and try again.",
};

function jsonBody(request) {
  if (
    request.headers["content-type"]?.split(";")[0].trim() !== "application/json"
  ) {
    throw new HttpError(415, "Send a JSON request.");
  }
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size <= 8192) chunks.push(chunk);
    });
    request.on("end", () => {
      if (size > 8192)
        return reject(new HttpError(413, "Request is too large."));
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (!body || Array.isArray(body) || typeof body !== "object")
          throw new Error();
        resolve(body);
      } catch {
        reject(new HttpError(422, "Enter valid form details."));
      }
    });
    request.on("error", () =>
      reject(new HttpError(400, "Request interrupted.")),
    );
  });
}

export async function createFrontend({
  apiBase = process.env.API_BASE_URL || "http://127.0.0.1:8000",
  origin = process.env.FRONTEND_ORIGIN ||
    "http://localhost:" + (process.env.FRONTEND_PORT || 3000),
  fetchApi = fetch,
} = {}) {
  const backend = new URL(apiBase);
  const publicUrl = new URL(origin);
  if (
    !["http:", "https:"].includes(backend.protocol) ||
    !["http:", "https:"].includes(publicUrl.protocol) ||
    backend.username ||
    backend.password ||
    publicUrl.username ||
    publicUrl.password
  ) {
    throw new Error(
      "API_BASE_URL and FRONTEND_ORIGIN must be HTTP(S) URLs without credentials.",
    );
  }
  if (
    process.env.NODE_ENV === "production" &&
    publicUrl.protocol !== "https:"
  ) {
    throw new Error("Production FRONTEND_ORIGIN requires HTTPS.");
  }
  const allowedHosts = new Set([publicUrl.host]);
  if (["localhost", "127.0.0.1"].includes(publicUrl.hostname)) {
    allowedHosts.add("localhost:" + (publicUrl.port || "80"));
    allowedHosts.add("127.0.0.1:" + (publicUrl.port || "80"));
  }
  const assets = new Map();
  for (const [path, type] of [
    ["/", "text/html; charset=utf-8"],
    ["/app.js", "text/javascript; charset=utf-8"],
    ["/styles.css", "text/css; charset=utf-8"],
  ]) {
    const file = path === "/" ? "index.html" : path.slice(1);
    assets.set(path, {
      type,
      content: await readFile(new URL("./public/" + file, import.meta.url)),
    });
  }
  const sessions = new Map();
  const cookieName = "rag_session";
  const cookie = (id, seconds) =>
    `${cookieName}=${id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${Math.max(0, Math.floor(seconds))}` +
    (publicUrl.protocol === "https:" ? "; Secure" : "");

  async function callApi(path, body, access) {
    let response;
    try {
      response = await fetchApi(new URL(path, backend), {
        method: body === undefined ? "GET" : "POST",
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(access ? { Authorization: "Bearer " + access } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      });
    } catch {
      throw new HttpError(
        503,
        "The API is unavailable. Make sure FastAPI and storage are running.",
      );
    }
    if (!response.ok) {
      throw new HttpError(
        response.status,
        messages[response.status] ||
          "The API is unavailable. Please try again.",
      );
    }
    return response.status === 204 ? null : response.json();
  }

  function updateTokens(session, tokens) {
    session.tokens = tokens;
    // Refresh a little early; token signatures and absolute expiry remain API-owned.
    session.accessUntil =
      Date.now() + Math.max(0, tokens.expires_in - 30) * 1000;
    session.expiresAt = Date.now() + tokens.refresh_expires_in * 1000;
  }

  async function profile(session) {
    const user = await callApi(
      "/auth/me",
      undefined,
      session.tokens.access_token,
    );
    return { ...user, tenant_id: session.tokens.tenant_id };
  }

  const cleanup = setInterval(() => {
    for (const [id, session] of sessions) {
      if (session.expiresAt <= Date.now()) sessions.delete(id);
    }
  }, 60000);
  cleanup.unref();

  const server = createServer(
    { requestTimeout: 15000, headersTimeout: 10000 },
    async (request, response) => {
      response.setHeader("Cache-Control", "no-store");
      response.setHeader("X-Content-Type-Options", "nosniff");
      response.setHeader("Referrer-Policy", "no-referrer");
      response.setHeader(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
      );
      let sessionId;
      try {
        if (!allowedHosts.has(request.headers.host))
          throw new HttpError(403, "Unrecognized host.");
        const path = new URL(request.url, publicUrl).pathname;
        if (request.method === "GET" && assets.has(path)) {
          const asset = assets.get(path);
          response.writeHead(200, { "Content-Type": asset.type });
          response.end(asset.content);
          return;
        }
        const route = request.method + " " + path;
        const routes = new Set([
          "POST /api/signup",
          "POST /api/login",
          "GET /api/session",
          "POST /api/tenants",
          "POST /api/select-tenant",
          "POST /api/logout",
        ]);
        if (!routes.has(route)) throw new HttpError(404, "Page not found.");
        if (request.method === "POST") {
          // Check the browser's exact origin before consuming credentials or cookies.
          const expected = publicUrl.protocol + "//" + request.headers.host;
          if (request.headers.origin !== expected)
            throw new HttpError(403, "Reload this page before submitting.");
        }
        const body =
          request.method === "POST" ? await jsonBody(request) : undefined;
        sessionId = request.headers.cookie
          ?.split(";")
          .map((s) => s.trim())
          .find((s) => s.startsWith(cookieName + "="))
          ?.slice(cookieName.length + 1);
        let session = sessions.get(sessionId);
        if (session && session.expiresAt <= Date.now()) {
          sessions.delete(sessionId);
          session = undefined;
        }
        let result;
        if (route === "POST /api/signup" || route === "POST /api/login") {
          if (session)
            throw new HttpError(
              409,
              "Sign out before using a different account.",
            );
          // Forward only this explicit auth route; this server is not an open proxy.
          const tokens = await callApi(
            route === "POST /api/signup" ? "/auth/signup" : "/auth/login",
            body,
          );
          session = { queue: Promise.resolve() };
          updateTokens(session, tokens);
          sessionId = randomBytes(32).toString("base64url");
          sessions.set(sessionId, session);
          response.setHeader(
            "Set-Cookie",
            cookie(sessionId, tokens.refresh_expires_in),
          );
          // Login is committed even if the subsequent profile read temporarily fails.
          result = { signed_in: true };
          console.info(
            JSON.stringify({
              level: "INFO",
              event: "frontend.session.created",
            }),
          );
        } else {
          if (!session) throw new HttpError(401, messages[401]);
          const work = session.queue.then(async () => {
            if (sessions.get(sessionId) !== session)
              throw new HttpError(401, messages[401]);
            if (route === "POST /api/logout") {
              // Preserve the session on API failure so the user can retry revocation.
              await callApi("/auth/logout", {
                refresh_token: session.tokens.refresh_token,
              });
              sessions.delete(sessionId);
              response.setHeader("Set-Cookie", cookie("", 0));
              console.info(
                JSON.stringify({
                  level: "INFO",
                  event: "frontend.session.revoked",
                }),
              );
              return { signed_in: false };
            }
            if (route === "POST /api/select-tenant") {
              updateTokens(
                session,
                await callApi("/auth/select-tenant", {
                  tenant_id: body.tenant_id,
                  refresh_token: session.tokens.refresh_token,
                }),
              );
            } else if (Date.now() >= session.accessUntil) {
              // A timeout after rotation is ambiguous: require login instead of replay.
              try {
                updateTokens(
                  session,
                  await callApi("/auth/refresh", {
                    refresh_token: session.tokens.refresh_token,
                  }),
                );
              } catch {
                sessions.delete(sessionId);
                throw new HttpError(
                  401,
                  "Your session could not be refreshed. Please sign in again.",
                );
              }
            }
            if (route === "POST /api/tenants") {
              const workspace = await callApi(
                "/tenants",
                body,
                session.tokens.access_token,
              );
              console.info(
                JSON.stringify({
                  level: "INFO",
                  event: "frontend.workspace.created",
                }),
              );
              return workspace;
            }
            return profile(session);
          });
          session.queue = work.catch(() => {});
          result = await work;
        }
        response.writeHead(
          route === "POST /api/signup" || route === "POST /api/tenants"
            ? 201
            : 200,
          { "Content-Type": "application/json; charset=utf-8" },
        );
        response.end(JSON.stringify(result));
      } catch (error) {
        const status = error instanceof HttpError ? error.status : 503;
        if (status === 401) {
          sessions.delete(sessionId);
          response.setHeader("Set-Cookie", cookie("", 0));
        }
        if (status >= 500)
          console.error(
            JSON.stringify({
              level: "ERROR",
              event: "frontend.request.failed",
              status,
            }),
          );
        response.writeHead(status, {
          "Content-Type": "application/json; charset=utf-8",
        });
        response.end(
          JSON.stringify({
            detail:
              error instanceof HttpError
                ? error.message
                : "Service unavailable. Please try again.",
          }),
        );
      }
    },
  );
  server.on("close", () => {
    clearInterval(cleanup);
    sessions.clear();
  });
  return server;
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const port = Number(process.env.FRONTEND_PORT || 3000);
  const server = await createFrontend();
  server.on("error", () => {
    console.error("Frontend could not start. Check that its port is free.");
    process.exitCode = 1;
    server.close();
  });
  server.listen(port, "127.0.0.1", () =>
    console.info("Frontend: http://localhost:" + port),
  );
}
