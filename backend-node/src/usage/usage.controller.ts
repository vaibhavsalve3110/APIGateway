import { Controller, Get, Param, ParseUUIDPipe, Query, UseGuards } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';

import { Roles, RolesGuard } from '../auth/roles.guard';
import { LogEntry, UsageLogsQueryDto, UsageQueryDto, UsageReport } from './usage.dto';
import { UsageService } from './usage.service';

@ApiTags('usage')
@ApiBearerAuth()
@Controller('api/admin/usage')
@UseGuards(AuthGuard('jwt'), RolesGuard)
@Roles('ADMIN', 'EDITOR', 'VIEWER')
export class UsageController {
  constructor(private readonly usage: UsageService) {}

  /** CP-RPT-01/02: filter by date-time range and Client ID; defaults to the last 15 minutes. */
  @Get('report')
  report(@Query() q: UsageQueryDto): Promise<UsageReport> {
    return this.usage.report(q.from, q.to, q.clientId);
  }

  /** Individual calls, newest first — the log viewer behind Management Portal › API Logs. */
  @Get('logs')
  logs(@Query() q: UsageLogsQueryDto): Promise<LogEntry[]> {
    return this.usage.logs(q.from, q.to, q.status ?? 'ALL', q.search, q.clientId, q.limit ?? 200);
  }

  /** CP-RPT-04: who depends on this API, from 30 days of traffic. */
  @Get('apis/:apiId/consumers')
  consumers(@Param('apiId', ParseUUIDPipe) apiId: string): Promise<string[]> {
    return this.usage.consumersOf(apiId);
  }
}
