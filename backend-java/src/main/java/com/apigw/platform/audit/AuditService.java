package com.apigw.platform.audit;

import java.time.Clock;
import java.util.List;

import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.security.Actor;

@Service
public class AuditService {

    private final AuditRepository repository;
    private final Clock clock;

    public AuditService(AuditRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    /** Recorded inside the caller's transaction, so an action and its audit entry commit or fail together. */
    @Transactional(propagation = Propagation.MANDATORY)
    public void record(Actor actor, String action, String objectType, Object objectId, String detail) {
        repository.save(new AuditEvent(clock.instant(), actor.username(), actor.primaryRole(), action, objectType,
                objectId == null ? null : String.valueOf(objectId), detail));
    }

    @Transactional(readOnly = true)
    public List<AuditEvent> latest(int limit) {
        return repository.findAllByOrderByOccurredAtDescIdDesc(PageRequest.of(0, Math.min(Math.max(limit, 1), 500)));
    }

    @Transactional(readOnly = true)
    public List<AuditEvent> forObject(String objectType, Object objectId) {
        return repository.findByObjectTypeAndObjectIdOrderByOccurredAtDescIdDesc(objectType, String.valueOf(objectId));
    }
}
