// Mints a token in backend-java's TokenService shape using the container stack's AUTH_JWT_SECRET
// from infra/.env. Prints only the token.
const crypto = require('crypto');
const fs = require('fs');

const env = fs.readFileSync('D:/Projects/API Gateway/api-gateway-platform/infra/.env', 'utf8');
const secret = /^AUTH_JWT_SECRET=(.*)$/m.exec(env)[1].trim();

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const now = Math.floor(Date.now() / 1000);

const email = process.argv[2] || 'admin@apigw.local';
const roles = (process.argv[3] || 'ADMIN').split(',');

const head = b64({ alg: 'HS256', typ: 'JWT' });
const body = b64({
  iss: 'apigw-platform',
  iat: now,
  exp: now + 3600,
  sub: email,
  preferred_username: email,
  name: 'Container Stack Check',
  realm_access: { roles },
});
const sig = crypto.createHmac('sha256', secret).update(`${head}.${body}`).digest('base64url');
process.stdout.write(`${head}.${body}.${sig}`);
