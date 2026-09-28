import { Module } from '@nestjs/common';

import { AuthModule } from '../auth/auth.module';
import { AuditController } from './audit.controller';
import { UsageController } from './usage.controller';
import { UsageService } from './usage.service';

@Module({
  imports: [AuthModule],
  controllers: [UsageController, AuditController],
  providers: [UsageService],
})
export class UsageModule {}
