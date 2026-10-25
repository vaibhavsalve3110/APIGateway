-- Partner registration is per organization: the signature key pair and the IPV salt belong to the
-- organization (like its security keys and Client IDs), not to each portal user. Users are logins.
--
-- Columns are nullable here because existing rows may have no material yet; PartnerCredentialBackfill
-- issues it at startup for any organization still without it, and new organizations get it on creation.

ALTER TABLE partner ADD COLUMN signature_algorithm   VARCHAR(40);
ALTER TABLE partner ADD COLUMN signature_public_key  VARCHAR(4000);
ALTER TABLE partner ADD COLUMN signature_fingerprint VARCHAR(120);
ALTER TABLE partner ADD COLUMN signature_created_at  TIMESTAMP WITH TIME ZONE;
ALTER TABLE partner ADD COLUMN ipv_salt_cipher       VARCHAR(500);
ALTER TABLE partner ADD COLUMN ipv_salt_masked       VARCHAR(60);
ALTER TABLE partner ADD COLUMN ipv_salt_created_at   TIMESTAMP WITH TIME ZONE;

-- Carry over the material of the organization's first user, so nothing already handed to a partner changes.
UPDATE partner p SET
    signature_algorithm   = (SELECT u.signature_algorithm   FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY),
    signature_public_key  = (SELECT u.signature_public_key  FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY),
    signature_fingerprint = (SELECT u.signature_fingerprint FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY),
    signature_created_at  = (SELECT u.signature_created_at  FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY),
    ipv_salt_cipher       = (SELECT u.ipv_salt_cipher       FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY),
    ipv_salt_masked       = (SELECT u.ipv_salt_masked       FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY),
    ipv_salt_created_at   = (SELECT u.ipv_salt_created_at   FROM partner_user u WHERE u.partner_id = p.id ORDER BY u.created_at FETCH FIRST 1 ROW ONLY)
WHERE EXISTS (SELECT 1 FROM partner_user u WHERE u.partner_id = p.id);

ALTER TABLE partner_user DROP COLUMN signature_algorithm;
ALTER TABLE partner_user DROP COLUMN signature_public_key;
ALTER TABLE partner_user DROP COLUMN signature_fingerprint;
ALTER TABLE partner_user DROP COLUMN signature_created_at;
ALTER TABLE partner_user DROP COLUMN ipv_salt_cipher;
ALTER TABLE partner_user DROP COLUMN ipv_salt_masked;
ALTER TABLE partner_user DROP COLUMN ipv_salt_created_at;
