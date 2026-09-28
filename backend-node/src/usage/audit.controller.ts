import { Controller, DefaultValuePipe, Get, ParseIntPipe, Query, UseGuards } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';

import { Roles, RolesGuard } from '../auth/roles.guard';
import { PrismaService } from '../prisma/prisma.service';

export interface AuditView {
  id: number;
  occurredAt: string;
  actor: string;
  actorRole: string | null;
  action: string;
  objectType: string;
  objectId: string | null;
  detail: string | null;
}

@ApiTags('audit')
@ApiBearerAuth()
@Controller('api/admin/audit')
@UseGuards(AuthGuard('jwt'), RolesGuard)
@Roles('ADMIN')
export class AuditController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async latest(
    @Query('limit', new DefaultValuePipe(100), ParseIntPipe) limit: number,
  ): Promise<AuditView[]> {
    const capped = Math.min(Math.max(limit, 1), 1000);
    const rows = await this.prisma.$queryRaw<
      {
        id: bigint;
        occurred_at: Date;
        actor: string;
        actor_role: string | null;
        action: string;
        object_type: string;
        object_id: string | null;
        detail: string | null;
      }[]
    >`
      SELECT id, occurred_at, actor, actor_role, action, object_type, object_id, detail
        FROM apim.audit_event
       ORDER BY occurred_at DESC, id DESC
       LIMIT ${capped}`;

    return rows.map((r) => ({
      id: Number(r.id),
      occurredAt: r.occurred_at.toISOString(),
      actor: r.actor,
      actorRole: r.actor_role,
      action: r.action,
      objectType: r.object_type,
      objectId: r.object_id,
      detail: r.detail,
    }));
  }
}
