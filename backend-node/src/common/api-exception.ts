import { HttpException, HttpStatus } from '@nestjs/common';

/**
 * A business-rule failure with a stable machine-readable code the portals react to — the Node
 * equivalent of backend-java's ApiException.
 *
 * Carrying the code here rather than in the message matters: the portals switch on `code`, and a
 * reworded message must never change behaviour.
 */
export class ApiException extends HttpException {
  // Named httpStatus, not status: HttpException already has a private `status`, and redeclaring it
  // is a compile error.
  readonly httpStatus: number;

  constructor(
    status: number,
    readonly code: string,
    message: string,
    readonly fields?: Record<string, string>,
  ) {
    super(message, status);
    this.httpStatus = status;
  }

  static notFound(what: string, id: unknown): ApiException {
    return new ApiException(HttpStatus.NOT_FOUND, 'NOT_FOUND', `${what} ${String(id)} was not found`);
  }

  static conflict(code: string, message: string): ApiException {
    return new ApiException(HttpStatus.CONFLICT, code, message);
  }

  static forbidden(code: string, message: string): ApiException {
    return new ApiException(HttpStatus.FORBIDDEN, code, message);
  }

  static badRequest(code: string, message: string): ApiException {
    return new ApiException(HttpStatus.BAD_REQUEST, code, message);
  }

  static validation(fields: Record<string, string>): ApiException {
    return new ApiException(
      HttpStatus.BAD_REQUEST,
      'VALIDATION_FAILED',
      'Some fields are invalid',
      fields,
    );
  }
}
