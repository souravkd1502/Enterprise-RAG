/** HTTP boundary tests use an in-process fake FastAPI; no MongoDB required. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { request } from 'node:http';
import { createFrontend } from '../server.mjs';

async function fixture(t, override) {
  const calls = [];
  let tokenNumber = 0;
  let selected = null;
  const workspaces = [];
  const tokens = (expires = 900) => ({
    access_token: 'private-access-' + (++tokenNumber),
    refresh_token: 'private-refresh-' + tokenNumber,
    expires_in: expires, refresh_expires_in: 3600,
    tenant_id: selected, user_id: 'user-1',
  });
  const fake = async (url, options) => {
    const path = url.pathname;
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ path, body, access: options.headers.Authorization });
    const intercepted = await override?.(path, body, tokens);
    if (intercepted) return intercepted;
    let data;
    switch (path) {
      case '/auth/signup':
      case '/auth/login':
      case '/auth/refresh': data = tokens(); break;
      case '/auth/me':
        data = { user_id: 'user-1', name: 'Alex', email: 'alex@example.com', auth_provider: 'local', workspaces };
        break;
      case '/tenants':
        data = { tenant_id: String(workspaces.length + 1), name: body.name, role: 'OWNER', status: 'active' };
        workspaces.push(data);
        break;
      case '/auth/select-tenant': selected = body.tenant_id; data = tokens(); break;
      case '/auth/logout': return new Response(null, { status: 204 });
      default: throw new Error('Unexpected API route');
    }
    return Response.json(data);
  };
  const server = await createFrontend({ fetchApi: fake });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => { server.closeAllConnections(); server.close(resolve); }));
  const send = (path, { method = 'GET', body, cookie, origin = 'http://localhost:3000' } = {}) =>
    new Promise((resolve, reject) => {
      const payload = typeof body === 'string' ? body : body === undefined ? null : JSON.stringify(body);
      const req = request({
        hostname: '127.0.0.1', port: server.address().port, path, method, agent: false,
        headers: {
          Host: 'localhost:3000', Origin: origin,
          ...(cookie ? { Cookie: cookie } : {}),
          ...(payload === null ? {} : { 'Content-Type': 'application/json' }),
        },
      }, (res) => {
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString();
          resolve({ status: res.statusCode, headers: res.headers, text,
            data: res.headers['content-type']?.includes('application/json') ? JSON.parse(text) : null });
        });
      });
      req.on('error', reject);
      req.end(payload);
    });
  const login = async () => {
    const response = await send('/api/login', { method: 'POST', body: {
      email: 'alex@example.com', password: 'a-long-enough-test-password',
    } });
    assert.equal(response.status, 200);
    return response.headers['set-cookie'][0].split(';')[0];
  };
  return { send, login, calls };
}

test('serves only frontend assets with security headers', async (t) => {
  const { send } = await fixture(t);
  const page = await send('/');
  assert.equal(page.status, 200);
  assert.match(page.text, /Create account/);
  assert.match(page.headers['content-security-policy'], /frame-ancestors 'none'/);
  assert.equal(page.headers['cache-control'], 'no-store');
  assert.equal((await send('/app.js')).status, 200);
  assert.equal((await send('/.env')).status, 404);
  assert.equal((await send('/../server.mjs')).status, 404);
});

test('rejects cross-origin submissions and oversized bodies before calling FastAPI', async (t) => {
  const { send, calls } = await fixture(t);
  const forbidden = await send('/api/login', { method: 'POST', body: {}, origin: 'https://other.example' });
  assert.equal(forbidden.status, 403);
  const large = await send('/api/signup', { method: 'POST', body: 'x'.repeat(8193) });
  assert.equal(large.status, 413);
  assert.equal(calls.length, 0);
});

test('signup, tenant creation/selection and logout never expose JWTs to the browser', async (t) => {
  const { send, calls } = await fixture(t);
  const signup = await send('/api/signup', { method: 'POST',
    body: { name: 'Alex', email: 'alex@example.com', password: 'a-long-enough-test-password' } });
  assert.equal(signup.status, 201);
  assert.doesNotMatch(signup.text, /private-access|private-refresh/);
  assert.match(signup.headers['set-cookie'][0], /HttpOnly; SameSite=Lax/);
  const cookie = signup.headers['set-cookie'][0].split(';')[0];
  assert.doesNotMatch(cookie, /private/);
  const initial = await send('/api/session', { cookie });
  assert.equal(initial.data.tenant_id, null);
  for (let i = 0; i < 2; i++) {
    const created = await send('/api/tenants', { method: 'POST', cookie, body: { name: 'Same name' } });
    assert.equal(created.status, 201);
  }
  const chosen = await send('/api/select-tenant', { method: 'POST', cookie, body: { tenant_id: '2' } });
  assert.equal(chosen.data.tenant_id, '2');
  assert.equal(chosen.data.workspaces.length, 2);
  assert.doesNotMatch(chosen.text, /private-access|private-refresh/);
  const logout = await send('/api/logout', { method: 'POST', cookie, body: {} });
  assert.equal(logout.status, 200);
  assert.match(logout.headers['set-cookie'][0], /Max-Age=0/);
  assert.equal((await send('/api/session', { cookie })).status, 401);
  assert.equal(calls.findLast((c) => c.path === '/auth/logout').body.refresh_token, 'private-refresh-2');
});

test('concurrent requests serialize automatic refresh instead of replaying a token', async (t) => {
  const { send, login, calls } = await fixture(t, async (path, body, tokens) => {
    if (path === '/auth/login') return Response.json(tokens(0));
    if (path === '/auth/refresh') {
      await new Promise((resolve) => setTimeout(resolve, 25));
      return Response.json(tokens());
    }
  });
  const cookie = await login();
  const results = await Promise.all([send('/api/session', { cookie }), send('/api/session', { cookie })]);
  assert.deepEqual(results.map((r) => r.status), [200, 200]);
  assert.equal(calls.filter((c) => c.path === '/auth/refresh').length, 1);
  assert.equal(calls.find((c) => c.path === '/auth/refresh').body.refresh_token, 'private-refresh-1');
});

test('ambiguous refresh failure discards the session instead of replaying credentials', async (t) => {
  const { send, login, calls } = await fixture(t, (path, body, tokens) => {
    if (path === '/auth/login') return Response.json(tokens(0));
    if (path === '/auth/refresh') throw new Error('private connection details');
  });
  const cookie = await login();
  const failed = await send('/api/session', { cookie });
  assert.equal(failed.status, 401);
  assert.match(failed.headers['set-cookie'][0], /Max-Age=0/);
  assert.doesNotMatch(failed.text, /private connection/);
  assert.equal((await send('/api/session', { cookie })).status, 401);
  assert.equal(calls.filter((c) => c.path === '/auth/refresh').length, 1);
});

test('failed logout can be retried and only confirmed revocation clears the session', async (t) => {
  let failLogout = true;
  const { send, login } = await fixture(t, (path) => {
    if (path === '/auth/logout' && failLogout) {
      failLogout = false;
      return Response.json({ detail: 'private driver message' }, { status: 503 });
    }
  });
  const cookie = await login();
  const failed = await send('/api/logout', { method: 'POST', cookie, body: {} });
  assert.equal(failed.status, 503);
  assert.doesNotMatch(failed.text, /private driver/);
  assert.equal((await send('/api/session', { cookie })).status, 200);
  assert.equal((await send('/api/logout', { method: 'POST', cookie, body: {} })).status, 200);
  assert.equal((await send('/api/session', { cookie })).status, 401);
});

test('backend-revoked access invalidates the browser session immediately', async (t) => {
  const { send, login } = await fixture(t, (path) =>
    path === '/auth/me' ? Response.json({ detail: 'Invalid session' }, { status: 401 }) : undefined);
  const cookie = await login();
  assert.equal((await send('/api/session', { cookie })).status, 401);
  const again = await send('/api/session', { cookie });
  assert.equal(again.status, 401);
  assert.match(again.headers['set-cookie'][0], /Max-Age=0/);
});
