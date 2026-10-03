import { Controller, Get, Param, ParseUUIDPipe, UseGuards } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';

import { Roles, RolesGuard } from '../auth/roles.guard';
import { ApisService } from './apis.service';
import { ApiView, GroupView, PartnerView } from './catalogue.dto';
import { PartnersService } from './partners.service';

@ApiTags('apis')
@ApiBearerAuth()
@Controller('api/admin/apis')
@UseGuards(AuthGuard('jwt'), RolesGuard)
@Roles('ADMIN', 'EDITOR', 'VIEWER')
export class ApisController {
  constructor(private readonly apis: ApisService) {}

  @Get()
  list(): Promise<ApiView[]> {
    return this.apis.list();
  }

  @Get(':id')
  get(@Param('id', ParseUUIDPipe) id: string): Promise<ApiView> {
    return this.apis.get(id);
  }
}

@ApiTags('partners')
@ApiBearerAuth()
@Controller('api/admin')
@UseGuards(AuthGuard('jwt'), RolesGuard)
@Roles('ADMIN', 'EDITOR', 'VIEWER')
export class PartnersController {
  constructor(private readonly partners: PartnersService) {}

  @Get('partner-groups')
  groups(): Promise<GroupView[]> {
    return this.partners.listGroups();
  }

  @Get('partners')
  list(): Promise<PartnerView[]> {
    return this.partners.listPartners();
  }

  @Get('partners/:id')
  get(@Param('id', ParseUUIDPipe) id: string): Promise<PartnerView> {
    return this.partners.getPartner(id);
  }
}
