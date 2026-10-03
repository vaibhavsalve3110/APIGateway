import { Injectable } from '@nestjs/common';

import { ApiException } from '../common/api-exception';
import { instantColumn, javaInstant } from '../common/time';
import { PrismaService } from '../prisma/prisma.service';
import { ApiDocumentation, ApiView } from './catalogue.dto';

/** CP-RPT-05: an API must stay Disabled for longer than this before it can be deleted. */
const COOLING_PERIOD_MS = 7 * 24 * 60 * 60 * 1000;

interface ApiRow {
  id: string;
  name: string;
  category: string;
  http_method: string;
  proxy_path: string;
  backend_url_sandbox: string;
  backend_url_production: string | null;
  status: string;
  guest_visible: boolean;
  rate_limit_count: number;
  rate_limit_window: string;
  owner_team: string | null;
  description: string | null;
  disabled_at: string | null;
  deletable_from: string | null;
  created_at: string;
  updated_at: string;
  documentation: string | null;
}

// deletableFrom is computed in SQL so it keeps the microsecond precision of disabled_at; doing the
// arithmetic on a JavaScript Date would round it to milliseconds and disagree with backend-java.
const API_COLUMNS = `
  id, name, category, http_method, proxy_path, backend_url_sandbox, backend_url_production,
  status, guest_visible, rate_limit_count, rate_limit_window, owner_team, description,
  ${instantColumn('disabled_at', 'disabled_at')},
  ${instantColumn(
    `CASE WHEN status = 'DISABLED' AND disabled_at IS NOT NULL
          THEN disabled_at + interval '7 days' END`,
    'deletable_from',
  )},
  ${instantColumn('created_at', 'created_at')},
  ${instantColumn('updated_at', 'updated_at')},
  documentation`;

@Injectable()
export class ApisService {
  constructor(private readonly prisma: PrismaService) {}

  async list(): Promise<ApiView[]> {
    const rows = await this.prisma.$queryRawUnsafe<ApiRow[]>(
      `SELECT ${API_COLUMNS} FROM api_definition ORDER BY name ASC`,
    );
    return rows.map((r) => this.toView(r));
  }

  async get(id: string): Promise<ApiView> {
    const rows = await this.prisma.$queryRawUnsafe<ApiRow[]>(
      `SELECT ${API_COLUMNS} FROM api_definition WHERE id = $1::uuid`,
      id,
    );
    const row = rows[0];
    if (!row) throw ApiException.notFound('API', id);
    return this.toView(row);
  }

  private toView(r: ApiRow): ApiView {
    return {
      id: r.id,
      name: r.name,
      category: r.category,
      httpMethod: r.http_method,
      proxyPath: r.proxy_path,
      backendUrlSandbox: r.backend_url_sandbox,
      backendUrlProduction: r.backend_url_production,
      status: r.status,
      guestVisible: r.guest_visible,
      rateLimitCount: r.rate_limit_count,
      rateLimitWindow: r.rate_limit_window,
      ownerTeam: r.owner_team,
      description: r.description,
      disabledAt: javaInstant(r.disabled_at),
      deletableFrom: javaInstant(r.deletable_from),
      createdAt: javaInstant(r.created_at) as string,
      updatedAt: javaInstant(r.updated_at) as string,
      documentation: this.documentation(r.documentation),
    };
  }

  /** Stored as a JSON string by DocumentationCodec. A malformed blob must not fail the whole list. */
  private documentation(stored: string | null): ApiDocumentation | null {
    if (!stored) return null;
    try {
      return JSON.parse(stored) as ApiDocumentation;
    } catch {
      return null;
    }
  }
}

export { COOLING_PERIOD_MS };
