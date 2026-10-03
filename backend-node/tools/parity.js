// Compares a ported endpoint's JSON between backend-java (:8088) and backend-node (:8089),
// by talking to each container directly so nginx routing is not part of the test.
//
//   node parity.js /api/admin/apis /api/admin/partners ...
//
// Exits non-zero if any endpoint differs, printing the first differing paths.
const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');

const env = fs.readFileSync('D:/Projects/API Gateway/api-gateway-platform/infra/.env', 'utf8');
const secret = /^AUTH_JWT_SECRET=(.*)$/m.exec(env)[1].trim();

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const now = Math.floor(Date.now() / 1000);
const head = b64({ alg: 'HS256', typ: 'JWT' });
const body = b64({
  iss: 'apigw-platform', iat: now, exp: now + 3600,
  sub: 'admin@apigw.local', preferred_username: 'admin@apigw.local', name: 'Parity Check',
  realm_access: { roles: ['ADMIN'] },
});
const token = `${head}.${body}.${crypto.createHmac('sha256', secret).update(`${head}.${body}`).digest('base64url')}`;

// curl runs inside the nginx container, which can reach both backends by service name.
function fetchFrom(service, port, path) {
  const out = execFileSync('docker', [
    'compose', 'exec', '-T', 'nginx',
    'wget', '-q', '-O', '-', '--header', `Authorization: Bearer ${token}`,
    `http://${service}:${port}${path}`,
  ], { cwd: 'D:/Projects/API Gateway/api-gateway-platform/infra', encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  return JSON.parse(out);
}

// Walks both trees and reports every path whose value differs.
function diff(a, b, path = '', out = []) {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) out.push(`${path}: length ${a.length} vs ${b.length}`);
    for (let i = 0; i < Math.min(a.length, b.length); i++) diff(a[i], b[i], `${path}[${i}]`, out);
    return out;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (!(k in a)) out.push(`${path}.${k}: missing in JAVA`);
      else if (!(k in b)) out.push(`${path}.${k}: missing in NODE`);
      else diff(a[k], b[k], `${path}.${k}`, out);
    }
    return out;
  }
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    out.push(`${path}: java=${JSON.stringify(a)} node=${JSON.stringify(b)}`);
  }
  return out;
}

let failed = 0;
for (const path of process.argv.slice(2)) {
  let java, node;
  try { java = fetchFrom('backend-java', 8088, path); } catch (e) { console.log(`  FAIL ${path} — java: ${e.message.split('\n')[0]}`); failed++; continue; }
  try { node = fetchFrom('backend-node', 8089, path); } catch (e) { console.log(`  FAIL ${path} — node: ${e.message.split('\n')[0]}`); failed++; continue; }
  const d = diff(java, node);
  if (d.length === 0) {
    const n = Array.isArray(java) ? `${java.length} items` : 'object';
    console.log(`  MATCH ${path}  (${n})`);
  } else {
    failed++;
    console.log(`  DIFF  ${path}`);
    for (const line of d.slice(0, 12)) console.log(`          ${line}`);
    if (d.length > 12) console.log(`          ...and ${d.length - 12} more`);
  }
}
process.exit(failed ? 1 : 0);
