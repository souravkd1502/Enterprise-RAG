/**
 * Opt-in end-to-end HTTP test. Point TEST_FRONTEND_URL at a frontend whose API
 * uses a disposable MongoDB database: this test creates accounts/workspaces.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';

test('real API: signup, duplicate-name tenants, selection, logout and sign-in', {
  skip: !process.env.TEST_FRONTEND_URL,
}, async () => {
  const base = new URL(process.env.TEST_FRONTEND_URL);
  const email = 'frontend-' + randomUUID() + '@example.com';
  const password = 'Disposable-test-password-42!';
  let cookie;
  async function send(path, body) {
    const response = await fetch(new URL(path, base), {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        Origin: base.origin,
        ...(cookie ? { Cookie: cookie } : {}),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    const nextCookie = response.headers.get('set-cookie');
    if (nextCookie) cookie = nextCookie.split(';')[0];
    const text = await response.text();
    assert.doesNotMatch(text, /access_token|refresh_token/);
    return { status: response.status, data: JSON.parse(text), headers: response.headers };
  }
  const invalid = await send('/api/signup', { email, password: 'short', name: 'Frontend test' });
  assert.equal(invalid.status, 422);
  const signup = await send('/api/signup', { email, password, name: 'Frontend test' });
  assert.equal(signup.status, 201);
  assert.match(signup.headers.get('set-cookie'), /HttpOnly/);
  const profile = (await send('/api/session')).data;
  assert.equal(profile.email, email);
  assert.equal(profile.tenant_id, null);
  assert.equal(profile.workspaces.length, 0);
  const first = await send('/api/tenants', { name: 'Same workspace name' });
  const second = await send('/api/tenants', { name: 'Same workspace name' });
  assert.equal(first.status, 201);
  assert.equal(second.status, 201);
  assert.notEqual(first.data.tenant_id, second.data.tenant_id);
  const selected = await send('/api/select-tenant', { tenant_id: second.data.tenant_id });
  assert.equal(selected.status, 200);
  assert.equal(selected.data.tenant_id, second.data.tenant_id);
  assert.equal(selected.data.workspaces.length, 2);
  assert.equal(selected.data.workspaces[0].role, 'OWNER');
  const loggedInCookie = cookie;
  assert.equal((await send('/api/logout', {})).status, 200);
  cookie = loggedInCookie; // Replaying a browser cookie must fail after logout.
  assert.equal((await send('/api/session')).status, 401);
  const login = await send('/api/login', { email, password });
  assert.equal(login.status, 200);
  const again = (await send('/api/session')).data;
  assert.equal(again.user_id, profile.user_id);
  assert.equal(again.workspaces.length, 2);
  assert.equal(again.tenant_id, null); // Multiple workspaces need explicit selection.
  assert.equal((await send('/api/logout', {})).status, 200);
});
