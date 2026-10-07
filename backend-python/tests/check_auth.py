"""Phase 6 gate: sign in through Python and have Java accept the session, and the reverse.

Three properties matter more than response shape here:

* a token minted by one service must be accepted by the other. Being *similar* is not enough.
* a wrong code must still consume an attempt. If a rejection rolls the counter back, the limit
  never bites and guessing a six-digit code is free.
* an unregistered address must be refused the same way by both, and the CAPTCHA must be single use.

The code itself is read from the database rather than from an inbox: outbound SMTP is blocked here,
so nothing is delivered. Reading the stored hash would not do — the code is only ever hashed — so a
known code is planted for the verification tests and removed afterwards.
"""

import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")

failures = 0
planted: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def call(base: str, method: str, path: str, body=None, bearer: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
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


def psql(sql: str) -> str:
    password = re.search(r"^DB_PASSWORD=(.*)$", infra_env, re.M).group(1).strip()
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", f"PGPASSWORD={password}", "-e", "PGOPTIONS=--search_path=apim",
         "postgres:17-alpine", "psql",
         "postgresql://apigw@host.docker.internal:5432/apigw", "-Atc", sql],
        capture_output=True, text=True, timeout=180,
    )
    return (result.stdout + result.stderr).strip()


def plant_code(email: str, code: str, attempts: int = 0) -> str:
    """Insert a challenge whose code we know, since nothing is delivered on this network."""
    challenge_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=5)
    digest = hashlib.sha256(code.encode()).hexdigest()
    psql(
        "insert into otp_challenge (id, email, code_hash, created_at, expires_at, attempts, client_ip)"
        f" values ('{challenge_id}', '{email}', '{digest}',"
        f" '{now.isoformat()}', '{expires.isoformat()}', {attempts}, '127.0.0.1');"
    )
    planted.append(challenge_id)
    return challenge_id


try:
    # A real, active account: sign-in only works for one the platform knows.
    email = psql("select email from platform_user where status = 'ACTIVE' limit 1;").strip()
    check("there is an active platform account to sign in as", bool(email), email)
    partner_email = psql(
        "select u.email from partner_user u join partner p on p.id = u.partner_id"
        " where u.status = 'ACTIVE' and p.status = 'ACTIVE' limit 1;"
    ).strip()

    print("--- captcha")
    for service, base in (("java", JAVA), ("python", PYTHON)):
        code, challenge = call(base, "POST", "/api/auth/captcha")
        check(f"{service} issues a captcha", code == 200 and challenge.get("challengeId"), f"{code}")
        check(f"{service} returns a png data uri",
              challenge["image"].startswith("data:image/png;base64,")
              and len(challenge["image"]) > 500, challenge["image"][:40])
        check(f"{service} states a ttl", challenge["expiresInSeconds"] == 300,
              str(challenge.get("expiresInSeconds")))

    print("--- a wrong captcha is refused, and a captcha is single use")
    _, challenge = call(PYTHON, "POST", "/api/auth/captcha")
    code, problem = call(PYTHON, "POST", "/api/auth/otp/request",
                         {"email": email, "captchaId": challenge["challengeId"],
                          "captchaAnswer": "WRONG"})
    check("python refuses a wrong captcha answer",
          code == 400 and problem.get("code") == "CAPTCHA_FAILED", f"{code} {problem}")
    code, problem = call(PYTHON, "POST", "/api/auth/otp/request",
                         {"email": email, "captchaId": challenge["challengeId"],
                          "captchaAnswer": "WRONG"})
    check("the same captcha cannot be tried twice",
          code == 400 and problem.get("code") == "CAPTCHA_FAILED", f"{code} {problem}")
    code, problem = call(JAVA, "POST", "/api/auth/otp/request",
                         {"email": email, "captchaId": str(uuid.uuid4()), "captchaAnswer": "WRONG"})
    check("java refuses an unknown captcha the same way",
          code == 400 and problem.get("code") == "CAPTCHA_FAILED", f"{code} {problem}")

    print("--- an unregistered address")
    for service, base in (("java", JAVA), ("python", PYTHON)):
        _, c = call(base, "POST", "/api/auth/captcha")
        code, problem = call(base, "POST", "/api/auth/otp/request",
                             {"email": "nobody@parity-check.test",
                              "captchaId": c["challengeId"], "captchaAnswer": "WRONG"})
        # The captcha is checked before the address, so this is still CAPTCHA_FAILED on both.
        check(f"{service} checks the captcha before the address",
              code == 400 and problem.get("code") == "CAPTCHA_FAILED", f"{code} {problem}")

    print("--- verifying a code")
    psql(f"delete from otp_challenge where email = '{email}';")
    plant_code(email, "123456")
    code, signed_in = call(PYTHON, "POST", "/api/auth/otp/verify", {"email": email, "code": "123456"})
    check("python signs in with a correct code", code == 200 and signed_in.get("token"),
          f"{code} {signed_in}")
    python_token = signed_in.get("token") if code == 200 else None
    if python_token:
        check("the session names the account", signed_in["email"] == email, signed_in.get("email"))
        check("it carries the roles", bool(signed_in["roles"]), json.dumps(signed_in.get("roles")))
        check("the code cannot be used twice",
              call(PYTHON, "POST", "/api/auth/otp/verify",
                   {"email": email, "code": "123456"})[0] == 401)

    psql(f"delete from otp_challenge where email = '{email}';")
    plant_code(email, "654321")
    code, java_signed_in = call(JAVA, "POST", "/api/auth/otp/verify", {"email": email, "code": "654321"})
    check("java signs in with a correct code", code == 200 and java_signed_in.get("token"), f"{code}")
    java_token = java_signed_in.get("token") if code == 200 else None

    print("--- the tokens are interchangeable")
    if python_token and java_token:
        code, from_java = call(JAVA, "GET", "/api/auth/me", bearer=python_token)
        check("java accepts a session python issued", code == 200, f"{code} {from_java}")
        code, from_python = call(PYTHON, "GET", "/api/auth/me", bearer=java_token)
        check("python accepts a session java issued", code == 200, f"{code} {from_python}")

        _, java_me = call(JAVA, "GET", "/api/auth/me", bearer=java_token)
        _, python_me = call(PYTHON, "GET", "/api/auth/me", bearer=python_token)
        check("both describe the signed-in user identically", java_me == python_me,
              f"{java_me} vs {python_me}")

        code, admin_read = call(JAVA, "GET", "/api/admin/partners", bearer=python_token)
        check("a python-issued session can use the admin API on java", code == 200, f"{code}")

    print("--- a wrong code still costs an attempt")
    psql(f"delete from otp_challenge where email = '{email}';")
    challenge_id = plant_code(email, "111111")
    before = psql(f"select attempts from otp_challenge where id = '{challenge_id}';").strip()
    code, problem = call(PYTHON, "POST", "/api/auth/otp/verify", {"email": email, "code": "999999"})
    after = psql(f"select attempts from otp_challenge where id = '{challenge_id}';").strip()
    check("python rejects the wrong code",
          code == 401 and problem.get("code") == "INVALID_CODE", f"{code} {problem}")
    check("and the attempt was counted, not rolled back",
          before == "0" and after == "1", f"{before} -> {after}")

    code, _ = call(JAVA, "POST", "/api/auth/otp/verify", {"email": email, "code": "888888"})
    after_java = psql(f"select attempts from otp_challenge where id = '{challenge_id}';").strip()
    check("java counts it the same way", after_java == "2", f"{after} -> {after_java}")

    print("--- the attempt limit bites")
    psql(f"delete from otp_challenge where email = '{email}';")
    challenge_id = plant_code(email, "222222", attempts=5)
    code, problem = call(PYTHON, "POST", "/api/auth/otp/verify", {"email": email, "code": "222222"})
    check("python refuses a correct code once the attempts are spent",
          code == 401 and problem.get("code") == "INVALID_CODE", f"{code} {problem}")
    code, problem = call(JAVA, "POST", "/api/auth/otp/verify", {"email": email, "code": "222222"})
    check("java refuses it too", code == 401 and problem.get("code") == "INVALID_CODE",
          f"{code} {problem}")

    print("--- an expired code")
    psql(f"delete from otp_challenge where email = '{email}';")
    challenge_id = str(uuid.uuid4())
    past = datetime.now(UTC) - timedelta(minutes=30)
    psql(
        "insert into otp_challenge (id, email, code_hash, created_at, expires_at, attempts, client_ip)"
        f" values ('{challenge_id}', '{email}', '{hashlib.sha256(b'333333').hexdigest()}',"
        f" '{past.isoformat()}', '{(past + timedelta(minutes=5)).isoformat()}', 0, '127.0.0.1');"
    )
    planted.append(challenge_id)
    code, problem = call(PYTHON, "POST", "/api/auth/otp/verify", {"email": email, "code": "333333"})
    check("python refuses an expired code",
          code == 401 and problem.get("code") == "INVALID_CODE", f"{code} {problem}")

    if partner_email:
        print("--- a partner session carries its organization")
        psql(f"delete from otp_challenge where email = '{partner_email}';")
        plant_code(partner_email, "444444")
        code, partner_session = call(PYTHON, "POST", "/api/auth/otp/verify",
                                     {"email": partner_email, "code": "444444"})
        check("python signs a partner user in", code == 200 and partner_session.get("token"), f"{code}")
        if code == 200:
            check("the session names their organization", bool(partner_session["partnerCode"]),
                  str(partner_session.get("partnerCode")))
            check("and the role is PARTNER", partner_session["roles"] == ["PARTNER"],
                  json.dumps(partner_session.get("roles")))
            code, portal = call(JAVA, "GET", "/api/partner/me", bearer=partner_session["token"])
            check("java serves the Developer Portal with it", code == 200, f"{code} {portal}")

finally:
    print("--- cleanup")
    for challenge_id in planted:
        psql(f"delete from otp_challenge where id = '{challenge_id}';")
    print(f"  removed {len(planted)} planted challenge(s)")
    left = psql(
        "select count(*) from otp_challenge where client_ip = '127.0.0.1' and consumed_at is null;"
    )
    check("no planted challenges left behind", left.endswith("0"), left)

print()
print("FAILED" if failures else "all sign-in checks passed")
sys.exit(1 if failures else 0)
