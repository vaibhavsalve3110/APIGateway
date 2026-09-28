/**
 * Fails the boot rather than the first request. A service that starts without a database URL or a
 * signing secret only looks healthy until someone tries to sign in.
 */
export interface Env {
  NODE_ENV: string;
  PORT: number;
  DATABASE_URL: string;
  AUTH_JWT_SECRET: string;
}

const DEV_SECRET = 'apigw-local-development-jwt-signing-secret-32b';

export function validateEnv(raw: Record<string, unknown>): Env {
  const nodeEnv = String(raw.NODE_ENV ?? 'development');
  const production = nodeEnv === 'production';

  const databaseUrl = String(raw.DATABASE_URL ?? '');
  if (!databaseUrl) {
    throw new Error('DATABASE_URL must be set (postgresql://user:pass@host:5432/apigw?schema=apim)');
  }

  let secret = String(raw.AUTH_JWT_SECRET ?? '');
  if (!secret) {
    if (production) {
      throw new Error('AUTH_JWT_SECRET must be set in production: it verifies session tokens');
    }
    // Same fallback as TokenService.signingKey in backend-java, so a token minted by either service
    // is accepted by the other on a developer machine.
    secret = DEV_SECRET;
    console.warn(
      'AUTH_JWT_SECRET is not set — using the built-in DEVELOPMENT signing key. ' +
        'Anyone with this source can mint a session token.',
    );
  }
  if (secret.length < 32) {
    throw new Error('AUTH_JWT_SECRET must be at least 32 characters (HS256 needs 256 bits)');
  }

  return {
    NODE_ENV: nodeEnv,
    PORT: Number(raw.PORT ?? 8089),
    DATABASE_URL: databaseUrl,
    AUTH_JWT_SECRET: secret,
  };
}
