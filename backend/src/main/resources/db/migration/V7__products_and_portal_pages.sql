-- CP-API-09: a Product is a journey — an ordered set of APIs a partner calls to complete one business
-- outcome, where later steps depend on earlier ones. It carries a flow document explaining that dependency,
-- and is assigned to an organization (and optionally to named users inside it).
-- CP-API-10: informational pages for the Developer Portal, edited here and published when ready.

CREATE TABLE product (
    id               UUID          PRIMARY KEY,
    name             VARCHAR(120)  NOT NULL UNIQUE,
    slug             VARCHAR(140)  NOT NULL UNIQUE,   -- stable id in Developer Portal URLs
    summary          VARCHAR(300),                    -- one line, shown on the catalogue card
    description      VARCHAR(4000),
    -- The flow and dependency document: how the APIs fit together, shown to partners on the product page.
    journey_markdown VARCHAR(100000),
    status           VARCHAR(20)   NOT NULL,          -- DRAFT | PUBLISHED
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by       VARCHAR(120)  NOT NULL,
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at     TIMESTAMP WITH TIME ZONE
);

-- The steps of the journey, in order. depends_on_api_id records which earlier step must succeed first —
-- for example "confirm payment" needs the txnId that "initiate payment" returns.
CREATE TABLE product_step (
    product_id        UUID          NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    api_id            UUID          NOT NULL REFERENCES api_definition (id) ON DELETE CASCADE,
    position          INTEGER       NOT NULL,
    step_note         VARCHAR(500),
    depends_on_api_id UUID,
    PRIMARY KEY (product_id, api_id)
);

CREATE INDEX idx_product_step_api ON product_step (api_id);

-- Who may see a Product. partner_user_id null means the whole organization; a row per user narrows it to
-- named people inside that organization.
CREATE TABLE product_assignment (
    id              UUID         PRIMARY KEY,
    product_id      UUID         NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    partner_id      UUID         NOT NULL REFERENCES partner (id) ON DELETE CASCADE,
    partner_user_id UUID         REFERENCES partner_user (id) ON DELETE CASCADE,
    assigned_by     VARCHAR(120) NOT NULL,
    assigned_at     TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Duplicate assignments are refused by ProductAssignmentService rather than by a partial unique index,
-- which H2 (used by the tests) does not support.
CREATE INDEX idx_product_assignment_product ON product_assignment (product_id);
CREATE INDEX idx_product_assignment_partner ON product_assignment (partner_id);
CREATE INDEX idx_product_assignment_user ON product_assignment (partner_user_id);

-- One row per page; the text lives in portal_page_version so an edit never overwrites what partners see.
CREATE TABLE portal_page (
    id                 UUID          PRIMARY KEY,
    slug               VARCHAR(140)  NOT NULL UNIQUE,
    title              VARCHAR(160)  NOT NULL,
    category           VARCHAR(60)   NOT NULL,   -- Guides | Reference | Legal | ...
    status             VARCHAR(20)   NOT NULL,   -- DRAFT | PUBLISHED
    position           INTEGER       NOT NULL,   -- order in the Developer Portal menu
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by         VARCHAR(120)  NOT NULL,
    updated_at         TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at       TIMESTAMP WITH TIME ZONE,
    -- The version partners currently see; null until the page is published for the first time.
    published_version  UUID
);

CREATE TABLE portal_page_version (
    id            UUID           PRIMARY KEY,
    page_id       UUID           NOT NULL REFERENCES portal_page (id) ON DELETE CASCADE,
    version       INTEGER        NOT NULL,
    body_markdown VARCHAR(100000) NOT NULL,
    edited_by     VARCHAR(120)   NOT NULL,
    edited_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE (page_id, version)
);

CREATE INDEX idx_page_version_page ON portal_page_version (page_id, version DESC);
