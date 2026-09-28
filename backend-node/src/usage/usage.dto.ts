import { Transform, Type } from 'class-transformer';
import { IsIn, IsInt, IsISO8601, IsOptional, IsString, Max, Min } from 'class-validator';

/** Mirrors UsageService.StatusFilter in backend-java. */
export const STATUS_FILTERS = ['ALL', 'SUCCESS', 'CLIENT_ERROR', 'SERVER_ERROR', 'ERROR'] as const;
export type StatusFilter = (typeof STATUS_FILTERS)[number];

export const STATUS_RANGES: Record<StatusFilter, { min: number; max: number }> = {
  ALL: { min: 0, max: 999 },
  SUCCESS: { min: 0, max: 399 },
  CLIENT_ERROR: { min: 400, max: 499 },
  SERVER_ERROR: { min: 500, max: 599 },
  ERROR: { min: 400, max: 999 },
};

const blankToUndefined = ({ value }: { value: unknown }): unknown =>
  typeof value === 'string' && value.trim() === '' ? undefined : value;

export class UsageQueryDto {
  @IsOptional()
  @IsISO8601()
  @Transform(blankToUndefined)
  from?: string;

  @IsOptional()
  @IsISO8601()
  @Transform(blankToUndefined)
  to?: string;

  @IsOptional()
  @IsString()
  @Transform(blankToUndefined)
  clientId?: string;
}

export class UsageLogsQueryDto extends UsageQueryDto {
  @IsOptional()
  @IsIn(STATUS_FILTERS)
  @Transform(blankToUndefined)
  status?: StatusFilter;

  @IsOptional()
  @IsString()
  @Transform(blankToUndefined)
  search?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(1000)
  limit?: number = 200;
}

export interface ApiUsage {
  apiId: string | null;
  apiName: string;
  success: number;
  failed: number;
}

export interface UsageReport {
  from: string;
  to: string;
  totalSuccess: number;
  totalFailed: number;
  apis: ApiUsage[];
}

export interface LogEntry {
  id: number;
  occurredAt: string;
  apiId: string | null;
  apiName: string | null;
  httpMethod: string | null;
  proxyPath: string | null;
  environment: string | null;
  clientId: string | null;
  partnerName: string | null;
  partnerCode: string | null;
  statusCode: number;
  latencyMs: number;
}
