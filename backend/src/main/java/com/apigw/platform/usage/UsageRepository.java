package com.apigw.platform.usage;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface UsageRepository extends JpaRepository<UsageEvent, Long> {

    /** Per-API success / failure counts and latency (CP-RPT-01). Success = any status below 400. */
    interface ApiUsageRow {
        UUID getApiId();
        long getSuccess();
        long getFailed();
        Integer getMinLatency();
        Integer getMaxLatency();
        Double getAvgLatency();
    }

    @Query("""
            select u.apiId as apiId,
                   sum(case when u.statusCode < 400 then 1 else 0 end) as success,
                   sum(case when u.statusCode >= 400 then 1 else 0 end) as failed,
                   min(u.latencyMs) as minLatency,
                   max(u.latencyMs) as maxLatency,
                   avg(u.latencyMs) as avgLatency
            from UsageEvent u
            where u.occurredAt >= :from and u.occurredAt < :to
              and u.apiId is not null
              and u.clientId in :clientIds
            group by u.apiId
            """)
    List<ApiUsageRow> aggregateForClients(@Param("from") Instant from, @Param("to") Instant to,
                                          @Param("clientIds") Collection<String> clientIds);

    @Query("""
            select u.apiId as apiId,
                   sum(case when u.statusCode < 400 then 1 else 0 end) as success,
                   sum(case when u.statusCode >= 400 then 1 else 0 end) as failed,
                   min(u.latencyMs) as minLatency,
                   max(u.latencyMs) as maxLatency,
                   avg(u.latencyMs) as avgLatency
            from UsageEvent u
            where u.occurredAt >= :from and u.occurredAt < :to
              and u.apiId is not null
            group by u.apiId
            """)
    List<ApiUsageRow> aggregateAll(@Param("from") Instant from, @Param("to") Instant to);

    /** Partners/Client IDs that called an API in the window — the dependency view (CP-RPT-04). */
    @Query("""
            select distinct u.clientId from UsageEvent u
            where u.apiId = :apiId and u.occurredAt >= :from and u.clientId is not null
            """)
    List<String> clientsOfApi(@Param("apiId") UUID apiId, @Param("from") Instant from);

    @Modifying
    @Query("delete from UsageEvent u where u.occurredAt < :cutoff")
    int deleteOlderThan(@Param("cutoff") Instant cutoff);
}
