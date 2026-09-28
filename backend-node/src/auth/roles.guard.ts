import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  SetMetadata,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';

import { Principal } from './jwt.strategy';

const ROLES_KEY = 'apigw:roles';

/** Roles are the plain names from `realm_access.roles`: ADMIN, EDITOR, VIEWER, PARTNER. */
export const Roles = (...roles: string[]) => SetMetadata(ROLES_KEY, roles);

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const required = this.reflector.getAllAndOverride<string[] | undefined>(ROLES_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (!required || required.length === 0) {
      return true;
    }
    const user = context.switchToHttp().getRequest<{ user?: Principal }>().user;
    if (!user || !required.some((role) => user.roles.includes(role))) {
      throw new ForbiddenException({
        code: 'FORBIDDEN',
        message: `Requires one of: ${required.join(', ')}`,
      });
    }
    return true;
  }
}
