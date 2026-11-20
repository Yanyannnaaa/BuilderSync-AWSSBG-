import os
import re
from datetime import date, datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["DEV_PRINT_LOGIN_CODES"] = "false"
if os.path.exists("test.db"):
    os.remove("test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Department, User, UserRole  # noqa: E402
from app.services import email_service, storage_service  # noqa: E402

CODES: dict[str, str] = {}
SENT: list = []


@pytest.fixture(autouse=True)
def mocks(monkeypatch):
    def fake_send(to, subject, html, text=None):
        CODES[to] = re.search(r">(\d{6})<", html).group(1)

    monkeypatch.setattr("app.routers.auth.send_email", fake_send)
    monkeypatch.setattr(email_service, "_send_resend", lambda b, s, h: SENT.append((len(b), s)))
    monkeypatch.setattr(storage_service, "s3_configured", lambda: True)
    monkeypatch.setattr(storage_service, "upload_stream", lambda f, k, e: CODES.update(key=k))
    monkeypatch.setattr(storage_service, "presigned_download_url", lambda k, n: ("https://s3/x", 900))


def mkuser(sn, first, last, role=UserRole.MEMBER, title=None, is_admin=False, department=None):
    with SessionLocal() as db:
        db.add(User(student_number=sn, first_name=first, last_name=last, school_email=f"{sn}@jru.edu",
                    personal_email=f"{sn}@gmail.com", year_level=3, role=role, officer_title=title,
                    is_admin=is_admin, department=department))
        db.commit()


def login(email, personal=False):
    c = TestClient(app)
    assert c.post("/api/auth/request-code", json={"email": email, "send_to_personal": personal}).status_code == 200
    to = email.replace("@jru.edu", "@gmail.com") if personal else email
    r = c.post("/api/auth/verify", json={"email": email, "code": CODES[to]})
    assert r.status_code == 200, r.text
    return c, r.json()


def test_full_flow():
    with TestClient(app):  # trigger startup (create tables)
        pass
    mkuser("1001", "Pres", "Ident", UserRole.OFFICER, "President", is_admin=True)
    mkuser("1002", "Sec", "Retary", UserRole.OFFICER, "Secretary")
    mkuser("2001", "Juan", "Dela Cruz", department=Department.TECHNOLOGY)

    # ---- unauthenticated is rejected everywhere ----
    anon = TestClient(app)
    for path in ("/api/members", "/api/meetings", "/api/audit", "/api/me/profile", "/api/announcements", "/api/submissions"):
        assert anon.get(path).status_code == 401, path

    # ---- login ----
    assert anon.post("/api/auth/request-code", json={"email": "nobody@jru.edu"}).status_code == 200  # no enumeration
    assert anon.post("/api/auth/verify", json={"email": "2001@jru.edu", "code": "000000"}).status_code == 401
    admin, info = login("1001@jru.edu")
    assert info["redirect"] == "/admin"
    sec, _ = login("1002@jru.edu")
    member, minfo = login("2001@jru.edu", personal=True)  # fallback to personal email
    assert minfo["redirect"] == "/member"
    assert admin.get("/admin", follow_redirects=False).status_code == 200
    assert member.get("/admin", follow_redirects=False).status_code == 307
    assert anon.get("/member", follow_redirects=False).status_code == 307

    # ---- member is blocked from officer endpoints ----
    for path in ("/api/members", "/api/meetings", "/api/submissions"):
        assert member.get(path).status_code == 403, path
    assert member.get("/api/audit").status_code == 403
    assert sec.get("/api/audit").status_code == 403  # only admin sees audit log
    assert member.post("/api/announcements", json={"title": "x", "content": "y"}).status_code == 403

    # ---- privilege escalation guards + department filter ----
    row = "student_number,first_name,last_name,year_level,school_email,personal_email,role,department\n"
    row += "3001,Eve,Hacker,2,eve@jru.edu,eve@gmail.com,Officer,creatives\n3002,Ok,Member,2,ok@jru.edu,ok@gmail.com,Member,marketing\n"
    r = sec.post("/api/members/import-csv", files={"file": ("m.csv", row)}).json()
    assert r["created"] == 1 and "Admin" in r["errors"][0]["error"]
    assert len(sec.get("/api/members?department=Marketing").json()) == 1
    mid = {m["student_number"]: m["id"] for m in sec.get("/api/members").json()}
    assert sec.patch(f"/api/members/{mid['3002']}", json={"role": "Officer"}).status_code == 403
    assert admin.patch(f"/api/members/{mid['3002']}", json={"role": "Officer", "officer_title": "Chief of Ops", "department": "Operations"}).status_code == 200
    assert sec.delete(f"/api/members/{mid['1001']}").status_code == 403
    assert admin.delete(f"/api/members/{mid['1001']}").status_code == 409  # self
    assert admin.patch(f"/api/members/{mid['1001']}", json={"is_admin": False}).status_code == 409  # last admin

    # ---- upload uses session identity ----
    r = member.post("/api/submissions/upload", data={"requirement_type": "Consent_Form"},
                    files={"file": ("final_revised(2).pdf", b"%PDF")})
    assert r.status_code == 201, r.text
    exp = f"Y3_2001_DELA_CRUZ_JUAN_CONSENT_FORM_{date.today():%Y%m%d}.pdf"
    assert r.json()["standardized_filename"] == exp and CODES["key"] == f"submissions/Member/Consent_Form/{exp}"
    assert member.post("/api/submissions/upload", data={"requirement_type": "X"}, files={"file": ("a.exe", b"x")}).status_code == 415
    assert member.get("/api/submissions/preview-name?requirement_type=Proposal&ext=docx").json()["filename"].endswith(".docx")
    assert len(member.get("/api/submissions/mine").json()) == 1
    sid = member.get("/api/submissions/mine").json()[0]["id"]
    assert member.get(f"/api/submissions/{sid}/download").status_code == 403
    assert sec.get(f"/api/submissions/{sid}/download").status_code == 200

    # ---- attendance engine + member view ----
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        m = sec.post("/api/meetings", json={"title": f"M{i}", "meeting_date": (base + timedelta(days=i)).isoformat()}).json()
        r = sec.post(f"/api/meetings/{m['id']}/attendance", json={"records": [{"student_number": "2001", "status": "Absent"}]})
        assert r.status_code == 200, r.text
        if i == 1:
            assert r.json()["activity_changes"][0]["warning_queued"]
    assert r.json()["activity_changes"][0]["deactivated"]
    prof = member.get("/api/me/profile").json()
    assert prof["user"]["is_active"] is False and prof["attendance_rate"] == 0.0 and prof["absences"] == 3
    assert len(member.get("/api/me/attendance").json()) == 3  # inactive can still log in / view

    # ---- announcements: broadcast + role-aware feed ----
    r = sec.post("/api/announcements", json={"title": "Hi", "content": "Hello", "target_audience": "All"})
    assert r.status_code == 201 and r.json()["recipient_count"] >= 6
    sec.post("/api/announcements", json={"title": "Active", "content": "x", "target_audience": "Active_Only"})
    sec.post("/api/announcements", json={"title": "Off", "content": "x", "target_audience": "Officers_Only"})
    assert {a["title"] for a in member.get("/api/announcements").json()} == {"Hi"}  # inactive + not officer
    assert len(sec.get("/api/announcements").json()) == 3

    # ---- audit log ----
    actions = {a["action"] for a in admin.get("/api/audit?limit=500").json()}
    assert {"login", "login_failed", "member_import_csv", "member_update", "attendance_record", "announcement_post",
            "submission_upload", "submission_download"} <= actions

    # ---- logout kills session ----
    assert member.post("/api/auth/logout").status_code == 200
    assert member.get("/api/me/profile").status_code == 401


def test_code_lockout_and_throttle():
    mkuser("4001", "Lock", "Out")
    c = TestClient(app)
    c.post("/api/auth/request-code", json={"email": "4001@jru.edu"})
    good = CODES["4001@jru.edu"]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert c.post("/api/auth/verify", json={"email": "4001@jru.edu", "code": bad}).status_code == 401
    # correct code is rejected after 5 attempts
    assert c.post("/api/auth/verify", json={"email": "4001@jru.edu", "code": good}).status_code == 401


def test_batching():
    sizes = []
    import app.services.email_service as es
    es._send_resend = lambda b, s, h: sizes.append(len(b))
    es.send_batch_emails([f"u{i}@x.com" for i in range(120)] + ["U1@x.com"], "s", "h")
    assert sizes == [50, 50, 20]


def test_email_failure_is_audited_but_generic(monkeypatch):
    mkuser("5001", "Fail", "Mail")
    mkuser("5002", "Adm", "In", UserRole.OFFICER, is_admin=True)

    def boom(*a, **k):
        raise RuntimeError("MessageRejected: Email address is not verified")

    monkeypatch.setattr("app.routers.auth.send_email", boom)
    c = TestClient(app)
    r = c.post("/api/auth/request-code", json={"email": "5001@jru.edu"})
    assert r.status_code == 200 and "sent" in r.json()["detail"]  # page stays generic
    monkeypatch.setattr("app.routers.auth.send_email", lambda to, sub, html, text=None: CODES.update({to: re.search(r">(\d{6})<", html).group(1)}))
    admin, _ = login("5002@jru.edu")
    logs = admin.get("/api/audit?action=login_email_failed").json()
    assert logs and "not verified" in logs[0]["detail"]
