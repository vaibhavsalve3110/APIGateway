import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import { FastifyReply, FastifyRequest } from 'fastify';

import { ApiException } from './api-exception';
import { ERROR_SOURCE, ErrorLogService } from './error-log.service';

/** Reason phrases for the `title` field, matching what Spring's ProblemDetail emits. */
const TITLES: Record<number, string> = {
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  405: 'Method Not Allowed',
  409: 'Conflict',
  415: 'Unsupported Media Type',
  500: 'Internal Server Error',
};

interface Principal {
  username?: string;
}

/**
 * Every error leaves the API as an RFC 9457 problem document with a `code` property — the same
 * contract backend-java's GlobalExceptionHandler produces.
 *
 * The portals read `code`, `detail`, `title` and `fields` (see packages/ui/src/api.ts). Returning
 * Nest's default `{statusCode, message}` would leave them falling back to the HTTP status text, so
 * a user would see "Request failed" instead of the real reason.
 */
@Catch()
export class ProblemFilter implements ExceptionFilter {
  private readonly log = new Logger(ProblemFilter.name);

  constructor(private readonly errors: ErrorLogService) {}

  async catch(exception: unknown, host: ArgumentsHost): Promise<void> {
    const ctx = host.switchToHttp();
    const reply = ctx.getResponse<FastifyReply>();
    const request = ctx.getRequest<FastifyRequest & { user?: Principal }>();

    const { status, code, detail, fields } = this.describe(exception);

    // Field order and membership follow what Spring's ProblemDetail serialises: `instance` carries
    // the request path, and `type` is omitted while it is the default about:blank.
    const body: Record<string, unknown> = {
      detail,
      instance: request.url,
      status,
      title: TITLES[status] ?? 'Error',
      code,
    };
    if (fields) body.fields = fields;

    // A 4xx is the API working as designed (a duplicate name, a revoked key); only a 5xx is our fault.
    if (status >= 500) {
      this.log.error(`${code}: ${detail}`, exception instanceof Error ? exception.stack : undefined);
      const reference = await this.errors.record(ERROR_SOURCE.API, code, detail, exception, {
        actor: request.user?.username ?? null,
        request: `${request.method} ${request.url}`,
        clientIp: request.ip ?? null,
      });
      if (reference) body.reference = reference;
    }

    await reply.status(status).type('application/problem+json').send(body);
  }

  private describe(exception: unknown): {
    status: number;
    code: string;
    detail: string;
    fields?: Record<string, string>;
  } {
    if (exception instanceof ApiException) {
      return {
        status: exception.httpStatus,
        code: exception.code,
        detail: exception.message,
        fields: exception.fields,
      };
    }

    if (exception instanceof HttpException) {
      const status = exception.getStatus();
      const response = exception.getResponse();
      // Guards and pipes throw plain HttpExceptions; some carry {code, message} already.
      if (response && typeof response === 'object') {
        const r = response as { code?: string; message?: unknown; error?: string };
        const message = Array.isArray(r.message) ? r.message.join('; ') : r.message;
        return {
          status,
          code: r.code ?? this.defaultCode(status),
          detail: typeof message === 'string' && message ? message : exception.message,
        };
      }
      return { status, code: this.defaultCode(status), detail: exception.message };
    }

    return {
      status: HttpStatus.INTERNAL_SERVER_ERROR,
      code: 'INTERNAL_ERROR',
      detail:
        'Something went wrong on our side. Quote the reference to your administrator.',
    };
  }

  private defaultCode(status: number): string {
    switch (status) {
      case 401:
        return 'UNAUTHENTICATED';
      case 403:
        return 'FORBIDDEN';
      case 404:
        return 'ENDPOINT_NOT_FOUND';
      case 405:
        return 'METHOD_NOT_ALLOWED';
      default:
        return `HTTP_${status}`;
    }
  }
}
