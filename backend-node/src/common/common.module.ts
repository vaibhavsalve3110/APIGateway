import { Global, Module } from '@nestjs/common';

import { AuditService } from './audit.service';
import { ErrorLogService } from './error-log.service';

@Global()
@Module({
  providers: [ErrorLogService, AuditService],
  exports: [ErrorLogService, AuditService],
})
export class CommonModule {}
