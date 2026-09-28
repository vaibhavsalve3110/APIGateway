package com.apigw.platform.content;

import java.text.Normalizer;
import java.time.Clock;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.content.ContentDtos.PageLink;
import com.apigw.platform.content.ContentDtos.PageRequest;
import com.apigw.platform.content.ContentDtos.PageView;
import com.apigw.platform.content.ContentDtos.PublishedPageView;
import com.apigw.platform.content.ContentDtos.VersionView;
import com.apigw.platform.security.Actor;

/**
 * Developer Portal pages (BRD CP-API-10): write and edit here, publish when ready.
 *
 * <p>Editing never changes what partners see. Each save adds a version; publishing points the live page at
 * one. That means a half-written FAQ cannot appear on the portal by accident, and there is a record of what
 * was published and by whom.
 */
@Service
public class ContentService {

    static final String AUDIT_TYPE = "PORTAL_PAGE";

    private final PortalPageRepository pages;
    private final PortalPageVersionRepository versions;
    private final AuditService audit;
    private final Clock clock;

    public ContentService(PortalPageRepository pages, PortalPageVersionRepository versions, AuditService audit,
                          Clock clock) {
        this.pages = pages;
        this.versions = versions;
        this.audit = audit;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<PageView> list() {
        return pages.findAllByOrderByCategoryAscPositionAscTitleAsc().stream().map(this::toView).toList();
    }

    @Transactional(readOnly = true)
    public PageView view(UUID id) {
        return toView(require(id));
    }

    @Transactional
    public PageView create(PageRequest request, Actor actor) {
        String title = request.title().trim();
        PortalPage page = new PortalPage(UUID.randomUUID(), uniqueSlug(title, null), title,
                request.category().trim(), request.position() == null ? 0 : request.position(),
                actor.username(), clock.instant());
        PortalPage saved = pages.saveAndFlush(page);
        saveVersion(saved, request.bodyMarkdown() == null ? "" : request.bodyMarkdown(), actor);
        audit.record(actor, "CREATE", AUDIT_TYPE, saved.getId(), "Portal page " + title + " created as a draft");
        return toView(saved);
    }

    /** Saves the text as a new version and updates the page's details; the live page is untouched. */
    @Transactional
    public PageView update(UUID id, PageRequest request, Actor actor) {
        PortalPage page = require(id);
        String title = request.title().trim();
        String slug = title.equalsIgnoreCase(page.getTitle()) ? page.getSlug() : uniqueSlug(title, id);
        page.updateDetails(slug, title, request.category().trim(),
                request.position() == null ? page.getPosition() : request.position(), clock.instant());

        String body = request.bodyMarkdown() == null ? "" : request.bodyMarkdown();
        Optional<PortalPageVersion> latest = versions.findFirstByPageIdOrderByVersionDesc(id);
        boolean textChanged = latest.isEmpty() || !latest.get().getBodyMarkdown().equals(body);
        if (textChanged) {
            saveVersion(page, body, actor);
        }
        audit.record(actor, "UPDATE", AUDIT_TYPE, id,
                "Portal page " + title + " edited" + (textChanged ? " (new version saved)" : " (details only)"));
        return toView(page);
    }

    /** CP-API-10: makes the latest saved text the one partners see. */
    @Transactional
    public PageView publish(UUID id, Actor actor) {
        PortalPage page = require(id);
        PortalPageVersion latest = versions.findFirstByPageIdOrderByVersionDesc(id)
                .orElseThrow(() -> ApiException.conflict("PAGE_EMPTY", "Write something before publishing this page"));
        if (latest.getBodyMarkdown().isBlank()) {
            throw ApiException.conflict("PAGE_EMPTY", "Write something before publishing this page");
        }
        page.publish(latest, clock.instant());
        audit.record(actor, "PUBLISH", AUDIT_TYPE, id,
                "Portal page " + page.getTitle() + " published (version " + latest.getVersion() + ")");
        return toView(page);
    }

    @Transactional
    public PageView unpublish(UUID id, Actor actor) {
        PortalPage page = require(id);
        page.unpublish(clock.instant());
        audit.record(actor, "UNPUBLISH", AUDIT_TYPE, id,
                "Portal page " + page.getTitle() + " withdrawn from the Developer Portal");
        return toView(page);
    }

    @Transactional
    public void delete(UUID id, Actor actor) {
        PortalPage page = require(id);
        if (page.getStatus() == PageStatus.PUBLISHED) {
            throw ApiException.conflict("PAGE_PUBLISHED",
                    "Withdraw " + page.getTitle() + " from the Developer Portal before deleting it");
        }
        pages.delete(page);
        audit.record(actor, "DELETE", AUDIT_TYPE, id, "Portal page " + page.getTitle() + " deleted");
    }

    // ------------------------------------------------------------------ partner side

    @Transactional(readOnly = true)
    public List<PageLink> publishedMenu() {
        return pages.findByStatusOrderByCategoryAscPositionAscTitleAsc(PageStatus.PUBLISHED).stream()
                .map(p -> new PageLink(p.getSlug(), p.getTitle(), p.getCategory()))
                .toList();
    }

    @Transactional(readOnly = true)
    public PublishedPageView publishedPage(String slug) {
        PortalPage page = pages.findBySlug(slug)
                .filter(p -> p.getStatus() == PageStatus.PUBLISHED && p.getPublishedVersion() != null)
                .orElseThrow(() -> ApiException.notFound("Page", slug));
        PortalPageVersion version = versions.findById(page.getPublishedVersion())
                .orElseThrow(() -> ApiException.notFound("Page version", page.getPublishedVersion()));
        return new PublishedPageView(page.getSlug(), page.getTitle(), page.getCategory(),
                version.getBodyMarkdown(), page.getPublishedAt());
    }

    // ------------------------------------------------------------------ internals

    private PortalPage require(UUID id) {
        return pages.findById(id).orElseThrow(() -> ApiException.notFound("Page", id));
    }

    private void saveVersion(PortalPage page, String body, Actor actor) {
        int next = versions.findFirstByPageIdOrderByVersionDesc(page.getId())
                .map(v -> v.getVersion() + 1).orElse(1);
        versions.saveAndFlush(new PortalPageVersion(UUID.randomUUID(), page.getId(), next, body,
                actor.username(), clock.instant()));
    }

    private PageView toView(PortalPage page) {
        List<PortalPageVersion> history = versions.findByPageIdOrderByVersionDesc(page.getId());
        PortalPageVersion latest = history.isEmpty() ? null : history.getFirst();
        boolean unpublishedChanges = page.getStatus() == PageStatus.PUBLISHED && latest != null
                && !latest.getId().equals(page.getPublishedVersion());
        return new PageView(page.getId(), page.getSlug(), page.getTitle(), page.getCategory(), page.getStatus(),
                page.getPosition(), latest == null ? "" : latest.getBodyMarkdown(), unpublishedChanges,
                page.getCreatedAt(), page.getCreatedBy(), page.getUpdatedAt(), page.getPublishedAt(),
                history.stream()
                        .map(v -> new VersionView(v.getId(), v.getVersion(), v.getEditedBy(), v.getEditedAt(),
                                v.getId().equals(page.getPublishedVersion())))
                        .toList());
    }

    private String uniqueSlug(String title, UUID keepingId) {
        String base = Normalizer.normalize(title, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "")
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("(^-+|-+$)", "");
        if (base.isEmpty()) {
            base = "page";
        }
        for (int i = 1; ; i++) {
            String candidate = i == 1 ? base : base + "-" + i;
            Optional<PortalPage> existing = pages.findBySlug(candidate);
            if (existing.isEmpty() || existing.get().getId().equals(keepingId)) {
                return candidate;
            }
        }
    }
}
