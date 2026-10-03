import { Injectable, Logger } from '@nestjs/common';
import { randomUUID } from 'node:crypto';

import { PrismaService } from '../prisma/prisma.service';

/** Matches ErrorLogService in backend-java, so both services write the same table the same way. */
export const ERROR_SOURCE = {
  SMTP: 'SMTP',
  GATEWAY: 'GATEWAY',
  SCHEDULER: 'SCHEDULER',
  API: 'API',
} as const;

// Column widths from V6__error_event.sql. Writing past them fails the insert, which would lose the
// very error we are trying to record.
const MAX = { code: 60, message: 1000, detail: 8000, actor: 120, request: 300, clientIp: 60 };

function trim(value: string | null | undefined, max: number): string | null {
  if (value === null || value === undefined) return null;
  return value.length <= max ? value : `${value.slice(0, max - 3)}...`;
}

export interface ErrorContext {
  actor?: string | null;
  request?: string | null;
  clientIp?: string | null;
}

@Injectable()
export class ErrorLogService {
  private readonly log = new Logger(ErrorLogService.name);

  constructor(private readonly prisma: PrismaService) {}

  /**
   * Records a failure and returns the reference shown to the caller, or null if it could not be
   * stored. Recording must never throw: an error log that takes the request down with it is worse
   * than no error log.
   */
  async record(
    source: string,
    code: string,
    message: string,
    cause?: unknown,
    context: ErrorContext = {},
  ): Promise<string | null> {
    const reference = `ERR-${randomUUID().slice(0, 8).toUpperCase()}`;
    const detail = cause instanceof Error ? (cause.stack ?? cause.message) : cause ? String(cause) : null;
    try {
      await this.prisma.$executeRaw`
        INSERT INTO error_event (occurred_at, source, code, message, detail, actor, request, client_ip, reference)
        VALUES (now(), ${trim(source, 40)}, ${trim(code, MAX.code)}, ${trim(message, MAX.message)},
                ${trim(detail, MAX.detail)}, ${trim(context.actor, MAX.actor)},
                ${trim(context.request, MAX.request)}, ${trim(context.clientIp, MAX.clientIp)},
                ${reference})`;
      return reference;
    } catch (e) {
      this.log.error(`Could not record error ${reference}: ${String(e)}`);
      return null;
    }
  }
}
