import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PassportStrategy } from '@nestjs/passport';
import { ExtractJwt, Strategy } from 'passport-jwt';

/**
 * Accepts the session token minted by backend-java's TokenService: HS256, issuer `apigw-platform`,
 * subject and `preferred_username` both the e-mail address, roles under `realm_access.roles`, and a
 * partner's organization as `groups: ["/partners/<CODE>"]`.
 *
 * Both services must share AUTH_JWT_SECRET. That is what lets one portal session work against either
 * backend while the migration is in progress.
 */
export const JWT_ISSUER = 'apigw-platform';

export interface JwtPayload {
  sub: string;
  iss: string;
  preferred_username?: string;
  name?: string;
  realm_access?: { roles?: string[] };
  groups?: string[];
}

/** Who is calling, in the shape the rest of the service wants it. */
export interface Principal {
  username: string;
  displayName: string;
  roles: string[];
  /** The organization code for a partner user, or null for a platform user. */
  partnerCode: string | null;
}

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(config: ConfigService) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      ignoreExpiration: false,
      issuer: JWT_ISSUER,
      secretOrKey: config.getOrThrow<string>('AUTH_JWT_SECRET'),
    });
  }

  validate(payload: JwtPayload): Principal {
    const group = (payload.groups ?? []).find((g) => g.startsWith('/partners/'));
    return {
      username: payload.preferred_username ?? payload.sub,
      displayName: payload.name ?? payload.sub,
      roles: payload.realm_access?.roles ?? [],
      partnerCode: group ? group.slice('/partners/'.length) : null,
    };
  }
}
