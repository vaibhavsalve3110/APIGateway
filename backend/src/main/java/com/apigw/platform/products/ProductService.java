package com.apigw.platform.products;

import java.text.Normalizer;
import java.time.Clock;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.apigw.platform.apis.ApiDefinition;
import com.apigw.platform.apis.ApiRepository;
import com.apigw.platform.apis.ApiStatus;
import com.apigw.platform.audit.AuditService;
import com.apigw.platform.common.ApiException;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerRepository;
import com.apigw.platform.partnerusers.PartnerUser;
import com.apigw.platform.partnerusers.PartnerUserRepository;
import com.apigw.platform.products.ProductDtos.AssignRequest;
import com.apigw.platform.products.ProductDtos.AssignmentView;
import com.apigw.platform.products.ProductDtos.PartnerProductView;
import com.apigw.platform.products.ProductDtos.ProductRequest;
import com.apigw.platform.products.ProductDtos.ProductView;
import com.apigw.platform.products.ProductDtos.StepRequest;
import com.apigw.platform.products.ProductDtos.StepView;
import com.apigw.platform.security.Actor;

/**
 * Products: journeys made of dependent APIs (BRD CP-API-09).
 *
 * <p>A Product bundles the APIs needed for one business outcome, in the order they are called, with a note
 * per step and an optional dependency on an earlier step. It is assigned to an organization, or to named
 * users inside it, which is what makes it visible in the Developer Portal.
 *
 * <p>Visibility is not permission: what a partner may actually call is decided by their security key at the
 * gateway. Nothing here touches a gateway.
 */
@Service
public class ProductService {

    static final String AUDIT_TYPE = "PRODUCT";

    private final ProductRepository products;
    private final ProductAssignmentRepository assignments;
    private final ApiRepository apis;
    private final PartnerRepository partners;
    private final PartnerUserRepository partnerUsers;
    private final AuditService audit;
    private final Clock clock;

    public ProductService(ProductRepository products, ProductAssignmentRepository assignments, ApiRepository apis,
                          PartnerRepository partners, PartnerUserRepository partnerUsers, AuditService audit,
                          Clock clock) {
        this.products = products;
        this.assignments = assignments;
        this.apis = apis;
        this.partners = partners;
        this.partnerUsers = partnerUsers;
        this.audit = audit;
        this.clock = clock;
    }

    // ------------------------------------------------------------------ admin

    @Transactional(readOnly = true)
    public List<ProductView> list() {
        Map<UUID, ApiDefinition> byId = allApisById();
        return products.findAllByOrderByNameAsc().stream().map(p -> toView(p, byId)).toList();
    }

    @Transactional(readOnly = true)
    public ProductView view(UUID id) {
        return toView(require(id), allApisById());
    }

    @Transactional
    public ProductView create(ProductRequest request, Actor actor) {
        String name = request.name().trim();
        List<ProductStep> steps = validSteps(request.steps());
        Product product = new Product(UUID.randomUUID(), name, uniqueSlug(name, null), trim(request.summary()),
                trim(request.description()), trim(request.journeyMarkdown()), steps, actor.username(), clock.instant());
        Product saved = products.saveAndFlush(product);
        audit.record(actor, "CREATE", AUDIT_TYPE, saved.getId(),
                "Product " + name + " created as a draft journey of " + steps.size() + " step(s)");
        return toView(saved, allApisById());
    }

    @Transactional
    public ProductView update(UUID id, ProductRequest request, Actor actor) {
        Product product = require(id);
        String name = request.name().trim();
        List<ProductStep> steps = validSteps(request.steps());
        String slug = name.equalsIgnoreCase(product.getName()) ? product.getSlug() : uniqueSlug(name, id);
        product.update(name, slug, trim(request.summary()), trim(request.description()),
                trim(request.journeyMarkdown()), steps, clock.instant());
        audit.record(actor, "UPDATE", AUDIT_TYPE, id, "Product " + name + " updated; " + steps.size() + " step(s)");
        return toView(product, allApisById());
    }

    @Transactional
    public ProductView setPublished(UUID id, boolean publish, Actor actor) {
        Product product = require(id);
        if (publish) {
            product.publish(clock.instant());
        } else {
            product.unpublish(clock.instant());
        }
        audit.record(actor, publish ? "PUBLISH" : "UNPUBLISH", AUDIT_TYPE, id,
                "Product " + product.getName()
                        + (publish ? " published to assigned partners" : " withdrawn to draft"));
        return toView(product, allApisById());
    }

    @Transactional
    public void delete(UUID id, Actor actor) {
        Product product = require(id);
        if (product.getStatus() == ProductStatus.PUBLISHED) {
            throw ApiException.conflict("PRODUCT_PUBLISHED",
                    "Withdraw " + product.getName() + " from the Developer Portal before deleting it");
        }
        assignments.deleteAll(assignments.findByProductId(id));
        products.delete(product);
        audit.record(actor, "DELETE", AUDIT_TYPE, id, "Product " + product.getName() + " deleted");
    }

    // ------------------------------------------------------------------ assignment

    /** CP-API-09: give an organization — or one named user inside it — sight of this journey. */
    @Transactional
    public ProductView assign(UUID productId, AssignRequest request, Actor actor) {
        Product product = require(productId);
        Partner partner = partners.findById(request.partnerId())
                .orElseThrow(() -> ApiException.notFound("Partner", request.partnerId()));

        PartnerUser user = null;
        if (request.partnerUserId() != null) {
            user = partnerUsers.findById(request.partnerUserId())
                    .orElseThrow(() -> ApiException.notFound("Partner user", request.partnerUserId()));
            if (!user.getPartnerId().equals(partner.getId())) {
                throw ApiException.conflict("USER_NOT_IN_ORGANIZATION",
                        user.getEmail() + " does not belong to " + partner.getName());
            }
            if (assignments.existsByProductIdAndPartnerUserId(productId, user.getId())) {
                throw ApiException.conflict("ALREADY_ASSIGNED",
                        product.getName() + " is already assigned to " + user.getEmail());
            }
        } else if (assignments.existsByProductIdAndPartnerIdAndPartnerUserIdIsNull(productId, partner.getId())) {
            throw ApiException.conflict("ALREADY_ASSIGNED",
                    product.getName() + " is already assigned to " + partner.getName());
        }

        assignments.saveAndFlush(new ProductAssignment(UUID.randomUUID(), productId, partner.getId(),
                user == null ? null : user.getId(), actor.username(), clock.instant()));
        audit.record(actor, "ASSIGN", AUDIT_TYPE, productId, "Product " + product.getName() + " assigned to "
                + (user == null ? partner.getName() + " (whole organization)" : user.getEmail() + " at " + partner.getName()));
        return toView(product, allApisById());
    }

    @Transactional
    public ProductView unassign(UUID productId, UUID assignmentId, Actor actor) {
        Product product = require(productId);
        ProductAssignment assignment = assignments.findById(assignmentId)
                .filter(a -> a.getProductId().equals(productId))
                .orElseThrow(() -> ApiException.notFound("Assignment", assignmentId));
        String who = describe(assignment);
        assignments.delete(assignment);
        audit.record(actor, "UNASSIGN", AUDIT_TYPE, productId,
                "Product " + product.getName() + " withdrawn from " + who);
        return toView(product, allApisById());
    }

    // ------------------------------------------------------------------ partner side

    /**
     * Published Products this partner can see: those assigned to the organization, plus any assigned to this
     * user personally. Only live APIs are listed — a disabled API is not something to send anyone to.
     */
    @Transactional(readOnly = true)
    public List<PartnerProductView> forPartner(UUID partnerId, String userEmail) {
        Optional<PartnerUser> user = userEmail == null ? Optional.empty()
                : partnerUsers.findByEmail(userEmail.toLowerCase(Locale.ROOT));
        Set<UUID> organizationWide = assignments.findByPartnerIdAndPartnerUserIdIsNull(partnerId).stream()
                .map(ProductAssignment::getProductId).collect(Collectors.toSet());
        Set<UUID> personal = user.map(u -> assignments.findByPartnerUserId(u.getId()).stream()
                .map(ProductAssignment::getProductId).collect(Collectors.toSet())).orElse(Set.of());

        Map<UUID, ApiDefinition> byId = allApisById();
        Set<UUID> visible = new LinkedHashSet<>(organizationWide);
        visible.addAll(personal);
        return products.findByStatusOrderByNameAsc(ProductStatus.PUBLISHED).stream()
                .filter(p -> visible.contains(p.getId()))
                .map(p -> new PartnerProductView(p.getId(), p.getName(), p.getSlug(), p.getSummary(),
                        p.getDescription(), p.getJourneyMarkdown(), steps(p, byId, true), personal.contains(p.getId())))
                .toList();
    }

    @Transactional(readOnly = true)
    public PartnerProductView forPartner(UUID partnerId, String userEmail, String slug) {
        return forPartner(partnerId, userEmail).stream()
                .filter(p -> p.slug().equals(slug))
                .findFirst()
                .orElseThrow(() -> ApiException.notFound("Product", slug));
    }

    // ------------------------------------------------------------------ internals

    private Product require(UUID id) {
        return products.findById(id).orElseThrow(() -> ApiException.notFound("Product", id));
    }

    /**
     * Keeps the author's order, drops repeated APIs, and checks the dependencies make sense: an API must
     * exist, may not depend on itself, and may only depend on another step of the same journey.
     */
    private List<ProductStep> validSteps(List<StepRequest> requested) {
        List<StepRequest> unique = new ArrayList<>();
        Set<UUID> seen = new LinkedHashSet<>();
        for (StepRequest step : requested) {
            if (step.apiId() != null && seen.add(step.apiId())) {
                unique.add(step);
            }
        }
        List<UUID> known = apis.findAllById(seen).stream().map(ApiDefinition::getId).toList();
        Optional<UUID> missing = seen.stream().filter(id -> !known.contains(id)).findFirst();
        if (missing.isPresent()) {
            throw ApiException.notFound("API", missing.get());
        }
        for (StepRequest step : unique) {
            UUID dependsOn = step.dependsOnApiId();
            if (dependsOn == null) {
                continue;
            }
            if (dependsOn.equals(step.apiId())) {
                throw ApiException.conflict("SELF_DEPENDENCY", "A step cannot depend on itself");
            }
            if (!seen.contains(dependsOn)) {
                throw ApiException.conflict("DEPENDENCY_NOT_IN_PRODUCT",
                        "A step can only depend on another API in the same product");
            }
        }
        return unique.stream().map(s -> new ProductStep(s.apiId(), s.note(), s.dependsOnApiId())).toList();
    }

    private Map<UUID, ApiDefinition> allApisById() {
        return apis.findAll().stream().collect(Collectors.toMap(ApiDefinition::getId, Function.identity()));
    }

    private static List<StepView> steps(Product product, Map<UUID, ApiDefinition> byId, boolean liveOnly) {
        List<StepView> out = new ArrayList<>();
        int number = 1;
        for (ProductStep step : product.getSteps()) {
            ApiDefinition api = byId.get(step.getApiId());
            if (api == null || (liveOnly && api.getStatus() != ApiStatus.ACTIVE)) {
                continue;
            }
            ApiDefinition dependsOn = step.getDependsOnApiId() == null ? null : byId.get(step.getDependsOnApiId());
            out.add(new StepView(number++, api.getId(), api.getName(), api.getCategory(), api.getHttpMethod(),
                    api.getProxyPath(), api.getStatus(), api.getDescription(), step.getNote(),
                    step.getDependsOnApiId(), dependsOn == null ? null : dependsOn.getName()));
        }
        return out;
    }

    private ProductView toView(Product p, Map<UUID, ApiDefinition> byId) {
        Map<UUID, Partner> partnersById = partners.findAll().stream()
                .collect(Collectors.toMap(Partner::getId, Function.identity()));
        List<AssignmentView> assigned = assignments.findByProductId(p.getId()).stream()
                .map(a -> {
                    Partner partner = partnersById.get(a.getPartnerId());
                    PartnerUser user = a.getPartnerUserId() == null ? null
                            : partnerUsers.findById(a.getPartnerUserId()).orElse(null);
                    return new AssignmentView(a.getId(), a.getPartnerId(),
                            partner == null ? null : partner.getCode(), partner == null ? null : partner.getName(),
                            a.getPartnerUserId(), user == null ? null : user.getEmail(),
                            a.getAssignedBy(), a.getAssignedAt());
                })
                .sorted((x, y) -> Objects.compare(x.partnerName(), y.partnerName(),
                        java.util.Comparator.nullsLast(String::compareTo)))
                .toList();
        return new ProductView(p.getId(), p.getName(), p.getSlug(), p.getSummary(), p.getDescription(),
                p.getJourneyMarkdown(), p.getStatus(), steps(p, byId, false), assigned,
                p.getCreatedAt(), p.getCreatedBy(), p.getUpdatedAt(), p.getPublishedAt());
    }

    private String describe(ProductAssignment assignment) {
        if (assignment.isWholeOrganization()) {
            return partners.findById(assignment.getPartnerId()).map(Partner::getName).orElse("an organization");
        }
        return partnerUsers.findById(assignment.getPartnerUserId()).map(PartnerUser::getEmail).orElse("a user");
    }

    private static String trim(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    /** Slugs appear in Developer Portal URLs, so they stay lower-case, hyphenated and unique. */
    private String uniqueSlug(String name, UUID keepingId) {
        String base = Normalizer.normalize(name, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "")
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("(^-+|-+$)", "");
        if (base.isEmpty()) {
            base = "product";
        }
        for (int i = 1; ; i++) {
            String candidate = i == 1 ? base : base + "-" + i;
            Optional<Product> existing = products.findBySlug(candidate);
            if (existing.isEmpty() || existing.get().getId().equals(keepingId)) {
                return candidate;
            }
        }
    }
}
