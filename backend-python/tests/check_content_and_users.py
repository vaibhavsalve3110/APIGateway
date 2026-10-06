"""Proves the ported Content and Partner Users modules against the Java ones.

Both tables are small or empty in a developer database, so a plain list comparison proves almost
nothing. This creates temporary records through each service in turn, checks that one service reads
what the other wrote, that the refusals carry the same codes, and removes everything afterwards.

Existing records are never touched: every fixture is named with a ZZ prefix or an @parity-check.test
address, and the cleanup asserts none are left.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token, diff  # noqa: E402

JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
TOKEN = _token(["ADMIN"])

failures = 0


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


created_pages: list[tuple[str, str]] = []
created_users: list[tuple[str, str]] = []

try:
    # ================================================================ portal pages
    print("--- portal pages")
    body = {"title": "ZZ Parity Page Java", "category": "Guides", "bodyMarkdown": "# Hello\nfirst draft",
            "position": 7}
    code, java_page = call(JAVA, "POST", "/api/admin/pages", body)
    check("java creates a page", code == 201 and java_page.get("id"), f"{code}")
    created_pages.append((JAVA, java_page["id"]))

    _, from_java = call(JAVA, "GET", f"/api/admin/pages/{java_page['id']}")
    _, from_python = call(PYTHON, "GET", f"/api/admin/pages/{java_page['id']}")
    d = diff(from_java, from_python)
    check("both read a java-created page identically", not d, "; ".join(d[:6]))

    body["title"] = "ZZ Parity Page Python"
    code, py_page = call(PYTHON, "POST", "/api/admin/pages", body)
    check("python creates a page", code == 201 and py_page.get("id"), f"{code} {py_page}")
    created_pages.append((PYTHON, py_page["id"]))
    check("python wrote version 1", [v["version"] for v in py_page["versions"]] == [1],
          json.dumps(py_page["versions"]))
    check("python slugged the title", py_page["slug"] == "zz-parity-page-python", py_page["slug"])

    _, from_java = call(JAVA, "GET", f"/api/admin/pages/{py_page['id']}")
    d = diff(from_java, py_page)
    check("java reads a python-created page identically", not d, "; ".join(d[:6]))

    # Editing the same text again must not pile up identical versions.
    code, same = call(PYTHON, "PUT", f"/api/admin/pages/{py_page['id']}", body)
    check("re-saving identical text adds no version", len(same["versions"]) == 1,
          json.dumps(same["versions"]))

    body["bodyMarkdown"] = "# Hello\nsecond draft"
    code, edited = call(PYTHON, "PUT", f"/api/admin/pages/{py_page['id']}", body)
    check("changed text adds a version", len(edited["versions"]) == 2, json.dumps(edited["versions"]))

    code, published = call(PYTHON, "POST", f"/api/admin/pages/{py_page['id']}/publish")
    check("python publishes the latest version",
          code == 200 and published["status"] == "PUBLISHED"
          and published["unpublishedChanges"] is False
          and [v for v in published["versions"] if v["live"]][0]["version"] == 2,
          f"{code} {json.dumps(published)[:220]}")

    body["bodyMarkdown"] = "# Hello\nthird draft, not published"
    code, drafted = call(PYTHON, "PUT", f"/api/admin/pages/{py_page['id']}", body)
    check("editing after publishing flags unpublished changes",
          drafted["unpublishedChanges"] is True, json.dumps(drafted)[:200])

    code, problem = call(PYTHON, "DELETE", f"/api/admin/pages/{py_page['id']}")
    check("python refuses to delete a published page",
          code == 409 and problem.get("code") == "PAGE_PUBLISHED", f"{code} {problem}")

    code, empty = call(PYTHON, "POST", "/api/admin/pages",
                       {"title": "ZZ Empty Page", "category": "Guides", "bodyMarkdown": "   "})
    created_pages.append((PYTHON, empty["id"]))
    code, problem = call(PYTHON, "POST", f"/api/admin/pages/{empty['id']}/publish")
    check("python refuses to publish an empty page",
          code == 409 and problem.get("code") == "PAGE_EMPTY", f"{code} {problem}")
    code, problem = call(JAVA, "POST", f"/api/admin/pages/{empty['id']}/publish")
    check("java refuses it the same way",
          code == 409 and problem.get("code") == "PAGE_EMPTY", f"{code} {problem}")

    _, list_java = call(JAVA, "GET", "/api/admin/pages")
    _, list_python = call(PYTHON, "GET", "/api/admin/pages")
    d = diff(list_java, list_python)
    check("page lists match", not d, "; ".join(d[:6]))

    # ================================================================ partner users
    print("--- partner users")
    _, partners = call(JAVA, "GET", "/api/admin/partners")
    partner_id = partners[0]["id"]

    code, java_user = call(JAVA, "POST", f"/api/admin/partners/{partner_id}/users",
                           {"fullName": "ZZ Parity Java", "email": "zz-java@parity-check.test",
                            "role": "PARTNER_VIEWER"})
    check("java creates a partner user", code == 200 and java_user.get("id"), f"{code} {java_user}")
    created_users.append((JAVA, java_user["id"]))

    _, from_java = call(JAVA, "GET", f"/api/admin/partner-users/{java_user['id']}")
    _, from_python = call(PYTHON, "GET", f"/api/admin/partner-users/{java_user['id']}")
    d = diff(from_java, from_python)
    check("both read a java-created user identically", not d, "; ".join(d[:6]))

    code, py_user = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/users",
                         {"fullName": "ZZ Parity Python", "email": "ZZ-Python@Parity-Check.test",
                          "role": "PARTNER_DEVELOPER"})
    check("python creates a partner user", code == 200 and py_user.get("id"), f"{code} {py_user}")
    created_users.append((PYTHON, py_user["id"])) if py_user.get("id") else None
    check("python lower-cased the e-mail", py_user["email"] == "zz-python@parity-check.test",
          py_user["email"])

    _, from_java = call(JAVA, "GET", f"/api/admin/partner-users/{py_user['id']}")
    d = diff(from_java, py_user)
    check("java reads a python-created user identically", not d, "; ".join(d[:6]))

    code, problem = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/users",
                         {"fullName": "ZZ Clash", "email": "zz-java@parity-check.test",
                          "role": "PARTNER_VIEWER"})
    check("python refuses a duplicate e-mail",
          code == 409 and problem.get("code") == "EMAIL_IN_USE", f"{code} {problem}")

    code, problem = call(PYTHON, "DELETE", f"/api/admin/partner-users/{py_user['id']}")
    check("python refuses to delete a user whose access is live",
          code == 409 and problem.get("code") == "ACCESS_NOT_REVOKED", f"{code} {problem}")

    code, revoked = call(PYTHON, "POST", f"/api/admin/partner-users/{py_user['id']}/access",
                         {"status": "DISABLED"})
    check("python revokes access", code == 200 and revoked["status"] == "DISABLED", f"{code} {revoked}")

    code, again = call(PYTHON, "POST", f"/api/admin/partner-users/{py_user['id']}/access",
                       {"status": "DISABLED"})
    check("revoking twice is a no-op", code == 200 and again["status"] == "DISABLED", f"{code} {again}")

    code, updated = call(PYTHON, "PUT", f"/api/admin/partner-users/{py_user['id']}",
                         {"fullName": "ZZ Parity Python Renamed",
                          "email": "zz-python2@parity-check.test", "role": "PARTNER_ADMIN"})
    check("python updates name, e-mail and role",
          code == 200 and updated["email"] == "zz-python2@parity-check.test"
          and updated["role"] == "PARTNER_ADMIN", f"{code} {updated}")

    _, list_java = call(JAVA, "GET", "/api/admin/partner-users")
    _, list_python = call(PYTHON, "GET", "/api/admin/partner-users")
    d = diff(list_java, list_python)
    check("partner user lists match", not d, "; ".join(d[:6]))

    _, scoped_java = call(JAVA, "GET", f"/api/admin/partners/{partner_id}/users")
    _, scoped_python = call(PYTHON, "GET", f"/api/admin/partners/{partner_id}/users")
    d = diff(scoped_java, scoped_python)
    check("per-partner user lists match", not d, "; ".join(d[:6]))

finally:
    print("--- cleanup")
    for base, user_id in created_users:
        call(base, "POST", f"/api/admin/partner-users/{user_id}/access", {"status": "DISABLED"})
        code, _ = call(base, "DELETE", f"/api/admin/partner-users/{user_id}")
        print(f"  deleted user {user_id} -> {code}")
    for base, page_id in created_pages:
        call(base, "POST", f"/api/admin/pages/{page_id}/unpublish")
        code, _ = call(base, "DELETE", f"/api/admin/pages/{page_id}")
        print(f"  deleted page {page_id} -> {code}")

    _, users_left = call(JAVA, "GET", "/api/admin/partner-users")
    stragglers = [u["email"] for u in users_left if "parity-check.test" in u["email"]]
    check("no test users left behind", not stragglers, ", ".join(stragglers))
    _, pages_left = call(JAVA, "GET", "/api/admin/pages")
    stragglers = [p["title"] for p in pages_left if p["title"].startswith("ZZ ")]
    check("no test pages left behind", not stragglers, ", ".join(stragglers))

print()
print("FAILED" if failures else "all content and partner-user checks passed")
sys.exit(1 if failures else 0)
