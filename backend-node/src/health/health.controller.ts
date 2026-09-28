import { Controller, Get } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';

import { PrismaService } from '../prisma/prisma.service';

/**
 * Same path and shape as Spring Actuator's, so nginx, compose health checks and any load balancer
 * probe both backends identically.
 */
@ApiTags('health')
@Controller('actuator/health')
export class HealthController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async health(): Promise<{ status: string; components: Record<string, { status: string }> }> {
    let db = 'UP';
    try {
      await this.prisma.$queryRaw`SELECT 1`;
    } catch {
      db = 'DOWN';
    }
    return { status: db === 'UP' ? 'UP' : 'DOWN', components: { db: { status: db } } };
  }
}
