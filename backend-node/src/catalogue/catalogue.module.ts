import { Module } from '@nestjs/common';

import { AuthModule } from '../auth/auth.module';
import { ApisService } from './apis.service';
import { ApisController, PartnersController } from './catalogue.controller';
import { PartnersService } from './partners.service';

@Module({
  imports: [AuthModule],
  controllers: [ApisController, PartnersController],
  providers: [ApisService, PartnersService],
})
export class CatalogueModule {}
