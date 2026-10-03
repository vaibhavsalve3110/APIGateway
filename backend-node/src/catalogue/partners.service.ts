import { Injectable } from '@nestjs/common';

import { ApiException } from '../common/api-exception';
import { instantColumn, javaInstant } from '../common/time';
import { PrismaService } from '../prisma/prisma.service';
import { GroupView, PartnerView } from './catalogue.dto';

interface PartnerRow {
  id: string;
  code: string;
  name: string;
  group_id: string;
  group_name: string | null;
  access_tier: string;
  status: string;
  contact_email: string | null;
  client_id_sandbox: string;
  client_id_production: string | null;
  created_at: string;
  signature_algorithm: string | null;
  signature_fingerprint: string | null;
  signature_public_key: string | null;
  signature_created_at: string | null;
  ipv_salt_masked: string | null;
  ipv_salt_created_at: string | null;
}

const PARTNER_COLUMNS = `
  p.id, p.code, p.name, p.group_id, g.name AS group_name, p.access_tier, p.status, p.contact_email,
  p.client_id_sandbox, p.client_id_production,
  ${instantColumn('p.created_at', 'created_at')},
  p.signature_algorithm, p.signature_fingerprint, p.signature_public_key,
  ${instantColumn('p.signature_created_at', 'signature_created_at')},
  p.ipv_salt_masked,
  ${instantColumn('p.ipv_salt_created_at', 'ipv_salt_created_at')}`;

@Injectable()
export class PartnersService {
  constructor(private readonly prisma: PrismaService) {}

  async listGroups(): Promise<GroupView[]> {
    const rows = await this.prisma.$queryRaw<
      { id: string; name: string; description: string | null; status: string; partner_count: bigint }[]
    >`
      SELECT g.id, g.name, g.description, g.status,
             (SELECT COUNT(*) FROM partner p WHERE p.group_id = g.id) AS partner_count
        FROM partner_group g
       ORDER BY g.name ASC`;
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      description: r.description,
      status: r.status,
      // COUNT(*) comes back as a bigint; JSON.stringify refuses to serialise one.
      partnerCount: Number(r.partner_count),
    }));
  }

  async listPartners(): Promise<PartnerView[]> {
    const rows = await this.prisma.$queryRawUnsafe<PartnerRow[]>(`
      SELECT ${PARTNER_COLUMNS}
        FROM partner p
        LEFT JOIN partner_group g ON g.id = p.group_id
       ORDER BY p.name ASC`);
    return rows.map((r) => this.toView(r));
  }

  async getPartner(id: string): Promise<PartnerView> {
    const rows = await this.prisma.$queryRawUnsafe<PartnerRow[]>(
      `SELECT ${PARTNER_COLUMNS}
         FROM partner p
         LEFT JOIN partner_group g ON g.id = p.group_id
        WHERE p.id = $1::uuid`,
      id,
    );
    const row = rows[0];
    if (!row) throw ApiException.notFound('Partner', id);
    return this.toView(row);
  }

  private toView(r: PartnerRow): PartnerView {
    return {
      id: r.id,
      code: r.code,
      name: r.name,
      groupId: r.group_id,
      groupName: r.group_name,
      accessTier: r.access_tier,
      status: r.status,
      contactEmail: r.contact_email,
      clientIdSandbox: r.client_id_sandbox,
      clientIdProduction: r.client_id_production,
      createdAt: javaInstant(r.created_at) as string,
      signatureAlgorithm: r.signature_algorithm,
      signatureFingerprint: r.signature_fingerprint,
      signaturePublicKey: r.signature_public_key,
      signatureCreatedAt: javaInstant(r.signature_created_at),
      ipvSaltMasked: r.ipv_salt_masked,
      ipvSaltCreatedAt: javaInstant(r.ipv_salt_created_at),
    };
  }
}
