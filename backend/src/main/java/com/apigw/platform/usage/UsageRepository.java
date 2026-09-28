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

    /** Totals for a window, for the dashboard (CP-RPT-01). */
    interface WindowTotals {
        Long getSuccess();
        Long getFailed();
        Double getAvgLatency();
    }

    @Query("""
            select sum(case when u.statusCode < 400 then 1 else 0 end) as success,
                   sum(case when u.statusCode >= 400 then 1 else 0 end) as failed,
                   avg(u.latencyMs) as avgLatency
            from UsageEvent u
            where u.occurredAt >= :from
            """)
    WindowTotals totalsSince(@Param("from") Instant from);

    /**
     * Individual calls for the log viewer. Every filter is optional: a null client id or an empty API list
     * means "all", and the status range covers the 2xx / 4xx / 5xx buckets the portal offers.
     */
    @Query("""
            select u from UsageEvent u
            where u.occurredAt >= :from and u.occurredAt < :to
              and (:clientId is null or u.clientId = :clientId)
              and (:allApis = true or u.apiId in :apiIds)
              and u.statusCode >= :minStatus and u.statusCode <= :maxStatus
            order by u.occurredAt desc, u.id desc
            """)
    List<UsageEvent> search(@Param("from") Instant from, @Param("to") Instant to,
                            @Param("clientId") String clientId,
                            @Param("allApis") boolean allApis, @Param("apiIds") Collection<UUID> apiIds,
                            @Param("minStatus") int minStatus, @Param("maxStatus") int maxStatus,
                            org.springframework.data.domain.Pageable page);

    /** Calls per Client ID in a window — the "who is calling us" view. */
    interface ClientUsageRow {
        String getClientId();
        long getSuccess();
        long getFailed();
        Double getAvgLatency();
    }

    @Query("""
            select u.clientId as clientId,
                   sum(case when u.statusCode < 400 then 1 else 0 end) as success,
                   sum(case when u.statusCode >= 400 then 1 else 0 end) as failed,
                   avg(u.latencyMs) as avgLatency
            from UsageEvent u
            where u.occurredAt >= :from and u.clientId is not null
            group by u.clientId
            """)
    List<ClientUsageRow> aggregateByClientSince(@Param("from") Instant from);

    @Modifying
    @Query("delete from UsageEvent u where u.occurredAt < :cutoff")
    int deleteOlderThan(@Param("cutoff") Instant cutoff);
}
