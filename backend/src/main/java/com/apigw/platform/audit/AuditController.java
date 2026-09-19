package com.apigw.platform.audit;

import java.time.Instant;
import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/admin/audit")
class AuditController {

    private final AuditService audit;

    AuditController(AuditService audit) {
        this.audit = audit;
    }

    @GetMapping
    List<AuditView> latest(@RequestParam(defaultValue = "100") int limit) {
        return audit.latest(limit).stream().map(AuditView::of).toList();
    }

    record AuditView(long id, Instant occurredAt, String actor, String actorRole, String action,
                     String objectType, String objectId, String detail) {
        static AuditView of(AuditEvent e) {
            return new AuditView(e.getId(), e.getOccurredAt(), e.getActor(), e.getActorRole(), e.getAction(),
                    e.getObjectType(), e.getObjectId(), e.getDetail());
        }
    }
}
