package com.apigw.platform.portal;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.apigw.platform.content.ContentDtos.PageLink;
import com.apigw.platform.content.ContentDtos.PublishedPageView;
import com.apigw.platform.content.ContentService;
import com.apigw.platform.partners.Partner;
import com.apigw.platform.partners.PartnerService;
import com.apigw.platform.products.ProductDtos.PartnerProductView;
import com.apigw.platform.products.ProductService;
import com.apigw.platform.security.CurrentActor;

/**
 * What the Developer Portal shows besides APIs: the journeys (Products) assigned to this partner
 * (CP-API-09) and the published information pages (CP-API-10).
 *
 * <p>Scoping comes from the token, never from the request: a partner cannot ask for another organization's
 * products by changing a parameter.
 */
@RestController
@RequestMapping("/api/partner")
class PartnerContentController {

    private final ProductService products;
    private final ContentService content;
    private final PartnerService partners;

    PartnerContentController(ProductService products, ContentService content, PartnerService partners) {
        this.products = products;
        this.content = content;
        this.partners = partners;
    }

    @GetMapping("/products")
    List<PartnerProductView> products() {
        Partner partner = me();
        return products.forPartner(partner.getId(), CurrentActor.get().username());
    }

    @GetMapping("/products/{slug}")
    PartnerProductView product(@PathVariable String slug) {
        Partner partner = me();
        return products.forPartner(partner.getId(), CurrentActor.get().username(), slug);
    }

    /** The published pages, for the portal's Guides menu. */
    @GetMapping("/pages")
    List<PageLink> pages() {
        return content.publishedMenu();
    }

    @GetMapping("/pages/{slug}")
    PublishedPageView page(@PathVariable String slug) {
        return content.publishedPage(slug);
    }

    private Partner me() {
        return partners.requireByCode(CurrentActor.requirePartnerCode());
    }
}
