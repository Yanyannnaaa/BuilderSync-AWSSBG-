"""Create the first Admin.  Usage:
python -m app.seed_admin STUDENT_NO FIRST LAST SCHOOL_EMAIL PERSONAL_EMAIL [YEAR] [TITLE]
"""
import sys

from sqlalchemy import select

from app.database import SessionLocal, init_models
from app.models import User, UserRole


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print(__doc__)
        return 1
    sn, first, last, school, personal = argv[:5]
    year = int(argv[5]) if len(argv) > 5 else 4
    title = argv[6] if len(argv) > 6 else "President"
    init_models()
    with SessionLocal() as db:
        existing = db.scalars(select(User).where(User.school_email == school.lower())).first()
        if existing:
            existing.role, existing.is_admin, existing.officer_title = UserRole.OFFICER, True, title
            print(f"Promoted existing user {school} to Admin Officer")
        else:
            db.add(User(student_number=sn, first_name=first, last_name=last, school_email=school.lower(),
                        personal_email=personal.lower(), year_level=year, role=UserRole.OFFICER,
                        is_admin=True, officer_title=title))
            print(f"Created Admin Officer {school}")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
