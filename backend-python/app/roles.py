"""Who may do what, in one place.

Two internal roles, and the difference between them is the point of the approval workflow:

**ADMIN** does everything, and is the only role that can approve a change, manage partner
organizations, create Developer Portal users, or create APIM users and set their roles.

**DEVELOPER** works on APIs and reads the logs. They may create a draft and edit it freely — a draft
serves no traffic — but making an API live, changing one that is already live, or withdrawing one
raises a change request for an administrator instead of taking effect. They cannot see or touch
partner credentials, organizations, users, products or portal content.

Previously this role was called EDITOR and could do all of those things, publish included, with
nobody else involved. V8 renames it; these lists are what narrow it.

An approval needs a *different* administrator from the one who raised the request — four eyes, which
is what a process review of a SEBI-regulated entity expects. That rule lives in `change_requests.py`
because it is about a particular request rather than about a role.
"""

ADMIN = "ADMIN"
DEVELOPER = "DEVELOPER"
PARTNER = "PARTNER"

#: Everyone who signs in to the management portal.
PLATFORM = (ADMIN, DEVELOPER)

#: Reading the catalogue, the dashboard, the audit trail, the error log and the usage reports. A
#: developer needs all of it: it is how they see whether what they shipped is working.
READ_PLATFORM = PLATFORM

#: Drafting and editing APIs. What this *does* depends on the API's status — see api_admin.py.
WRITE_APIS = PLATFORM

#: Raising and withdrawing change requests, and reading the queue.
REQUEST_CHANGES = PLATFORM

#: Deciding a change request. Administrators only, and never one's own.
APPROVE_CHANGES = (ADMIN,)

#: Partner organizations, their credentials and their Developer Portal users; API products and
#: portal content; APIM users and their roles. All of it administrator-only now.
ADMIN_ONLY = (ADMIN,)
