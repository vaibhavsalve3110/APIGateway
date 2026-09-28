import { BadRequestException, Injectable } from '@nestjs/common';

import { PrismaService } from '../prisma/prisma.service';
import {
  ApiUsage,
  LogEntry,
  STATUS_RANGES,
  StatusFilter,
  UsageReport,
} from './usage.dto';

/** CP-RPT-01/02 default when no range is given, matching UsageService.DEFAULT_WINDOW. */
const DEFAULT_WINDOW_MS = 15 * 60 * 1000;
/** CP-RPT-03: usage data is held online for 30 days; a wider 'from' is clamped, not rejected. */
const RETENTION_MS = 30 * 24 * 60 * 60 * 1000;

@Injectable()
export class UsageService {
  constructor(private readonly prisma: PrismaService) {}

  /**
   * Resolves the window the same way backend-java does: 'to' defaults to now, 'from' to 15 minutes
   * before it, and a 'from' older than retention is pulled forward rather than returning a hole.
   */
  private window(from?: string, to?: string): { start: Date; end: Date } {
    const now = new Date();
    const end = to ? new Date(to) : now;
    const start = from ? new Date(from) : new Date(end.getTime() - DEFAULT_WINDOW_MS);
    if (!(start.getTime() < end.getTime())) {
      throw new BadRequestException({ code: 'INVALID_RANGE', message: "'from' must be before 'to'" });
    }
    const earliest = new Date(now.getTime() - RETENTION_MS);
    return { start: start < earliest ? earliest : start, end };
  }

  async report(from?: string, to?: string, clientId?: string): Promise<UsageReport> {
    const { start, end } = this.window(from, to);

    const rows = await this.prisma.$queryRaw<
      { api_id: string | null; api_name: string | null; success: bigint; failed: bigint }[]
    >`
      SELECT u.api_id,
             a.name AS api_name,
             COUNT(*) FILTER (WHERE u.status_code < 400) AS success,
             COUNT(*) FILTER (WHERE u.status_code >= 400) AS failed
        FROM apim.usage_event u
        LEFT JOIN apim.api_definition a ON a.id = u.api_id
       WHERE u.occurred_at >= ${start}
         AND u.occurred_at < ${end}
         AND (${clientId ?? null}::varchar IS NULL OR u.client_id = ${clientId ?? null})
       GROUP BY u.api_id, a.name
       ORDER BY success DESC, failed DESC`;

    const apis: ApiUsage[] = rows.map((r) => ({
      apiId: r.api_id,
      apiName: r.api_name ?? '(unknown API)',
      success: Number(r.success),
      failed: Number(r.failed),
    }));

    return {
      from: start.toISOString(),
      to: end.toISOString(),
      totalSuccess: apis.reduce((sum, a) => sum + a.success, 0),
      totalFailed: apis.reduce((sum, a) => sum + a.failed, 0),
      apis,
    };
  }

  async logs(
    from?: string,
    to?: string,
    status: StatusFilter = 'ALL',
    search?: string,
    clientId?: string,
    limit = 200,
  ): Promise<LogEntry[]> {
    const { start, end } = this.window(from, to);
    const range = STATUS_RANGES[status];
    const term = search?.trim() ? `%${search.trim().toLowerCase()}%` : null;

    const rows = await this.prisma.$queryRaw<
      {
        id: bigint;
        occurred_at: Date;
        api_id: string | null;
        api_name: string | null;
        http_method: string | null;
        proxy_path: string | null;
        environment: string | null;
        client_id: string | null;
        partner_name: string | null;
        partner_code: string | null;
        status_code: number;
        latency_ms: number;
      }[]
    >`
      SELECT u.id, u.occurred_at, u.api_id, a.name AS api_name, a.http_method, a.proxy_path,
             u.environment, u.client_id, p.name AS partner_name, p.code AS partner_code,
             u.status_code, u.latency_ms
        FROM apim.usage_event u
        LEFT JOIN apim.api_definition a ON a.id = u.api_id
        LEFT JOIN apim.partner p ON u.client_id IN (p.client_id_sandbox, p.client_id_production)
       WHERE u.occurred_at >= ${start}
         AND u.occurred_at < ${end}
         AND u.status_code BETWEEN ${range.min} AND ${range.max}
         AND (${clientId ?? null}::varchar IS NULL OR u.client_id = ${clientId ?? null})
         AND (${term}::varchar IS NULL
              OR LOWER(a.name) LIKE ${term} OR LOWER(a.proxy_path) LIKE ${term})
       ORDER BY u.occurred_at DESC, u.id DESC
       LIMIT ${limit}`;

    return rows.map((r) => ({
      id: Number(r.id),
      occurredAt: r.occurred_at.toISOString(),
      apiId: r.api_id,
      apiName: r.api_name,
      httpMethod: r.http_method,
      proxyPath: r.proxy_path,
      environment: r.environment,
      clientId: r.client_id,
      partnerName: r.partner_name,
      partnerCode: r.partner_code,
      statusCode: r.status_code,
      latencyMs: r.latency_ms,
    }));
  }

  /** CP-RPT-04: who has actually called this API inside the retention window. */
  async consumersOf(apiId: string): Promise<string[]> {
    const since = new Date(Date.now() - RETENTION_MS);
    const rows = await this.prisma.$queryRaw<{ name: string }[]>`
      SELECT DISTINCT p.name
        FROM apim.usage_event u
        JOIN apim.partner p ON u.client_id IN (p.client_id_sandbox, p.client_id_production)
       WHERE u.api_id = ${apiId}::uuid
         AND u.occurred_at >= ${since}
       ORDER BY p.name`;
    return rows.map((r) => r.name);
  }
}
