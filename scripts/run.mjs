/** Own both development processes, including cleanup of Windows Python children. */
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { createFrontend } from '../frontend/server.mjs';

const python = process.argv[2];
const extraArgs = process.argv.slice(3);
let apiPort = process.env.API_PORT || '8000';
for (let i = 0; i < extraArgs.length; i++) {
  if (extraArgs[i] === '--port') apiPort = extraArgs[i + 1];
  if (extraArgs[i].startsWith('--port=')) apiPort = extraArgs[i].slice(7);
}
apiPort = Number(apiPort);
const frontendPort = Number(process.env.FRONTEND_PORT || 3000);
if (!python || ![apiPort, frontendPort].every((port) => Number.isInteger(port) && port > 0 && port < 65536) ||
    apiPort === frontendPort) {
  console.error('Choose different valid API_PORT and FRONTEND_PORT values.');
  process.exit(1);
}

async function checkPort(port) {
  const probe = createServer();
  await new Promise((resolve, reject) => {
    probe.once('error', () => reject(new Error('Port ' + port + ' is in use. Stop the existing app or choose another port.')));
    probe.listen(port, '127.0.0.1', () => probe.close(resolve));
  });
}

let frontend;
let api;
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  frontend?.closeAllConnections();
  frontend?.close();
  if (api?.pid && api.exitCode === null) {
    if (process.platform === 'win32') {
      // Kill only the child tree this launcher created, including the venv shim.
      spawnSync('taskkill', ['/PID', String(api.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    } else {
      api.kill('SIGTERM');
    }
  }
  setTimeout(() => process.exit(code), 5000).unref();
}

try {
  await checkPort(apiPort);
  await checkPort(frontendPort);
  frontend = await createFrontend({
    apiBase: process.env.API_BASE_URL || 'http://127.0.0.1:' + apiPort,
    origin: process.env.FRONTEND_ORIGIN || 'http://localhost:' + frontendPort,
  });
  await new Promise((resolve, reject) => {
    frontend.once('error', reject);
    frontend.listen(frontendPort, '127.0.0.1', resolve);
  });
  api = spawn(python, ['-m', 'uvicorn', 'src.api.main:app', '--host', '127.0.0.1',
    '--port', String(apiPort), '--no-access-log', ...extraArgs], {
    cwd: fileURLToPath(new URL('../', import.meta.url)), stdio: 'inherit', windowsHide: true,
  });
  api.once('error', () => { console.error('Could not start Python. Check .venv.'); stop(1); });
  api.once('exit', (code) => stop(code ?? 1));
  process.once('SIGINT', () => stop(130));
  process.once('SIGTERM', () => stop(143));
  console.info('Frontend: http://localhost:' + frontendPort);
  console.info('Swagger:  http://127.0.0.1:' + apiPort + '/docs');
  console.info('Press Ctrl+C to stop both. Wait for API startup before signing in.');
} catch (error) {
  console.error(error.message);
  stop(1);
}
