/* No libraries, browser token storage, or HTML interpolation of account data. */
const $ = (id) => document.getElementById(id);
let mode = "login";
let user = null;
let busy = false;

function notice(message = "", error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
  $("notice").hidden = !message;
}

function showSignedOut() {
  user = null;
  $("auth-view").hidden = false;
  $("workspace-view").hidden = true;
  $("auth-form").reset();
  $("retry").hidden = true;
  $("tenant-form").reset();
  $("tenant-form").hidden = true;
  $("user-name").textContent = "";
  $("user-email").textContent = "";
  $("workspace-list").replaceChildren();
  changeMode("login");
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new Error(
      "Could not reach the app. Check your connection and try again.",
    );
  }
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) showSignedOut();
    const error = new Error(
      data.detail || "Something went wrong. Please try again.",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}

function renderWorkspaces() {
  $("tenant-form").hidden = false;
  $("user-name").textContent = user.name;
  $("user-email").textContent = user.email;
  $("workspace-count").textContent = user.workspaces.length;
  $("workspace-list").replaceChildren();
  $("empty-state").hidden = user.workspaces.length > 0;
  for (const workspace of user.workspaces) {
    const item = document.createElement("div");
    item.className = "workspace-item";
    const info = document.createElement("div");
    const name = document.createElement("p");
    name.className = "workspace-name";
    name.textContent = workspace.name;
    const role = document.createElement("p");
    role.className = "role";
    role.textContent = workspace.role === "OWNER" ? "Owner" : "Member";
    const id = document.createElement("span");
    id.className = "workspace-id";
    id.textContent = workspace.tenant_id;
    info.append(name, role, id);
    const open = document.createElement("button");
    const current = workspace.tenant_id === user.tenant_id;
    open.type = "button";
    open.textContent = current ? "✓ Active" : "Open";
    open.className = current ? "current" : "secondary";
    open.disabled = current || busy;
    if (current) open.dataset.current = "true";
    open.setAttribute(
      "aria-label",
      (current ? "Active workspace: " : "Open workspace: ") + workspace.name,
    );
    open.addEventListener("click", () =>
      perform(async () => {
        user = await api("/api/select-tenant", {
          tenant_id: workspace.tenant_id,
        });
        renderWorkspaces();
        notice(workspace.name + " is now your active workspace.");
      }),
    );
    item.append(info, open);
    $("workspace-list").append(item);
  }
}

async function loadSession() {
  $("retry").hidden = true;
  try {
    user = await api("/api/session");
    $("auth-view").hidden = true;
    $("workspace-view").hidden = false;
    renderWorkspaces();
    return true;
  } catch (error) {
    // A missing session is the normal initial state, not an error banner.
    if (error.status === 401) return false;
    $("retry").hidden = false;
    throw error;
  } finally {
    $("loading").hidden = true;
  }
}

async function perform(action) {
  if (busy) return;
  busy = true;
  notice();
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = true;
  });
  document.querySelectorAll("input").forEach((input) => {
    input.disabled = true;
  });
  try {
    await action();
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy = false;
    document.querySelectorAll("button").forEach((button) => {
      button.disabled = button.hasAttribute("data-current");
    });
    document.querySelectorAll("input").forEach((input) => {
      input.disabled = false;
    });
  }
}

function changeMode(next) {
  mode = next;
  const signup = mode === "signup";
  $("auth-title").textContent = signup
    ? "Make room for your ideas."
    : "Welcome back.";
  $("auth-description").textContent = signup
    ? "Create your account, then add your first workspace."
    : "Sign in to your account and pick up where you left off.";
  $("auth-submit").textContent = signup ? "Create account" : "Sign in";
  $("name-field").hidden = !signup;
  $("name").required = signup;
  $("password").autocomplete = signup ? "new-password" : "current-password";
  $("password").value = "";
  $("password").type = "password";
  $("toggle-password").textContent = "Show";
  $("toggle-password").setAttribute("aria-pressed", "false");
  for (const tab of ["login", "signup"]) {
    $(tab + "-tab").classList.toggle("active", mode === tab);
    $(tab + "-tab").setAttribute("aria-pressed", String(mode === tab));
  }
  notice();
}

$("login-tab").addEventListener("click", () => changeMode("login"));
$("signup-tab").addEventListener("click", () => changeMode("signup"));
$("toggle-password").addEventListener("click", () => {
  const visible = $("password").type === "password";
  $("password").type = visible ? "text" : "password";
  $("toggle-password").textContent = visible ? "Hide" : "Show";
  $("toggle-password").setAttribute("aria-pressed", String(visible));
});

$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const body = {
    email: $("email").value.trim(),
    password: $("password").value,
  };
  if (mode === "signup") {
    body.name = $("name").value.trim();
    if (!body.name) return notice("Please enter your name.", true);
  }
  if (
    Array.from(body.password).length < 15 ||
    Array.from(body.password).length > 128
  ) {
    return notice("Your password must contain 15–128 characters.", true);
  }
  perform(async () => {
    await api("/api/" + mode, body);
    $("auth-form").reset();
    $("auth-view").hidden = true;
    $("workspace-view").hidden = false;
    await loadSession();
  });
});

$("tenant-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = $("workspace-name").value.trim();
  if (!name) return notice("Please enter a workspace name.", true);
  perform(async () => {
    const workspace = await api("/api/tenants", { name });
    user.workspaces.push(workspace);
    $("tenant-form").reset();
    renderWorkspaces();
    notice("Workspace created. Choose Open to make it active.");
  });
});

$("logout").addEventListener("click", () =>
  perform(async () => {
    await api("/api/logout", {});
    showSignedOut();
    notice("You have been signed out.");
  }),
);
$("retry").addEventListener("click", () => perform(loadSession));
perform(loadSession);
