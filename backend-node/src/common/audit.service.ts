import { Injectable } from '@nestjs/common';

import { PrismaService } from '../prisma/prisma.service';

/**
 * Appends to the same audit_event table backend-java writes, with the same column widths, so the
 * Management Portal's audit view cannot tell which service performed the action.
 */
const MAX = { actor: 120, actorRole: 30, action: 40, objectType: 40, objectId: 80, detail: 1000 };

function trim(value: string | null | undefined, max: number): string | null {
  if (value === null || value === undefined) return null;
  return value.length <= max ? value : `${value.slice(0, max - 3)}...`;
}

@Injectable()
export class AuditService {
  constructor(private readonly prisma: PrismaService) {}

  async record(entry: {
    actor: string;
    actorRole?: string | null;
    action: string;
    objectType: string;
    objectId?: string | null;
    detail?: string | null;
  }): Promise<void> {
    await this.prisma.$executeRaw`
      INSERT INTO audit_event (occurred_at, actor, actor_role, action, object_type, object_id, detail)
      VALUES (now(), ${trim(entry.actor, MAX.actor)}, ${trim(entry.actorRole, MAX.actorRole)},
              ${trim(entry.action, MAX.action)}, ${trim(entry.objectType, MAX.objectType)},
              ${trim(entry.objectId, MAX.objectId)}, ${trim(entry.detail, MAX.detail)})`;
  }
}
