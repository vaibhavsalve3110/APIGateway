-- CP-PTN-03: a product mapping records the authority for it.
--
-- Giving a partner organization sight of a product is an access decision, and the question an
-- auditor asks is not "who clicked it" — the audit trail already answers that — but "who authorised
-- it". So every assignment now carries a reference to that authority: a ticket number, an e-mail
-- subject, a signed-note id, whatever the organization uses.
--
-- It is free text on purpose. The platform cannot verify a ticket number, and pretending to (by
-- validating a format that will change) would buy nothing. What it can do is refuse to create a
-- mapping without one, which is what makes the trail complete.
--
-- Added nullable and then made NOT NULL, rather than NOT NULL with a default: a default would mean
-- every existing row silently claims an authority it does not have. Any row already present is
-- backfilled with a marker that says exactly that, so an old mapping is distinguishable from one
-- made under the new rule.

ALTER TABLE product_assignment ADD COLUMN approval_reference VARCHAR(200);

UPDATE product_assignment
   SET approval_reference = 'UNRECORDED — mapped before CP-PTN-03 evidence was required'
 WHERE approval_reference IS NULL;

ALTER TABLE product_assignment ALTER COLUMN approval_reference SET NOT NULL;

COMMENT ON COLUMN product_assignment.approval_reference IS
    'CP-PTN-03: the authority for this mapping — a ticket, e-mail or note reference. Free text.';
