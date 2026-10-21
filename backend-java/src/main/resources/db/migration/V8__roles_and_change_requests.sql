-- APIM roles become ADMIN and DEVELOPER, and publishing goes through an approval.
--
-- Two things happen here:
--
-- 1. EDITOR is renamed to DEVELOPER. It was already the "someone who works on APIs" role, but it
--    could publish an API, edit a live one and manage partners and partner users with nobody else
--    involved. The name now matches what it is, and the permissions are narrowed in the services.
--    VIEWER is not introduced: the Python service accepted it in its role lists but the Java enum
--    never defined it, so no row has ever held it.
--
-- 2. change_request records a proposed change waiting for an administrator. A developer may create
--    and edit a draft freely — a draft serves no traffic — but making an API live, changing one that
--    is already live, and withdrawing one all go through here. Without the second of those the
--    approval would be decorative: a developer could leave an API in draft and simply edit the live
--    one instead.
--
-- The proposed change is stored whole, as the JSON body the request would have carried, rather than
-- as columns per field. The live row is then untouched until somebody approves, which is the point:
-- the API goes on serving its approved definition while a change waits.

UPDATE platform_user SET role = 'DEVELOPER', updated_at = now() WHERE role = 'EDITOR';

COMMENT ON COLUMN platform_user.role IS 'ADMIN | DEVELOPER';

CREATE TABLE change_request (
    id            UUID          PRIMARY KEY,
    -- API today. Kept general because portal pages and products have the same publish step and are
    -- the obvious next candidates.
    object_type   VARCHAR(30)   NOT NULL,
    -- Null for a change that would create something, which nothing does yet: an API is created as a
    -- draft and only its publishing is reviewed.
    object_id     UUID,
    -- PUBLISH | UPDATE | DISABLE
    action        VARCHAR(30)   NOT NULL,
    -- The proposed definition, as the API's own request body. Null for PUBLISH and DISABLE, which
    -- change only the status.
    payload       JSONB,
    -- One line for the approver's list, written when the request is raised: which API, what changes.
    summary       VARCHAR(400)  NOT NULL,
    -- PENDING | APPROVED | REJECTED | WITHDRAWN
    status        VARCHAR(20)   NOT NULL,
    requested_by  VARCHAR(200)  NOT NULL,
    requested_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    -- Must differ from requested_by: an approval is a second pair of eyes or it is nothing. Enforced
    -- in the services, where the message can explain itself, rather than by a constraint that would
    -- surface as an opaque integrity error.
    decided_by    VARCHAR(200),
    decided_at    TIMESTAMP WITH TIME ZONE,
    decision_note VARCHAR(1000)
);

-- The approvals screen opens on everything still waiting, newest first.
CREATE INDEX idx_change_request_pending ON change_request (status, requested_at DESC);

-- "Is there already a change waiting on this API?" — asked before accepting another one, so two
-- developers cannot queue conflicting edits to the same API.
CREATE INDEX idx_change_request_object ON change_request (object_type, object_id, status);
