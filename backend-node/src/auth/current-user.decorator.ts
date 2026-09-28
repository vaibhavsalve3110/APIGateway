import { ExecutionContext, createParamDecorator } from '@nestjs/common';

import { Principal } from './jwt.strategy';

export const CurrentUser = createParamDecorator(
  (_data: unknown, context: ExecutionContext): Principal =>
    context.switchToHttp().getRequest<{ user: Principal }>().user,
);
