# BuilderSync – Organization Management & Secretary Portal

```
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in DB / AWS / email / SECRET_KEY
python -m app.seed_admin STUDENT_NO FIRST LAST SCHOOL_EMAIL PERSONAL_EMAIL [YEAR] [TITLE]
uvicorn app.main:app --reload
pytest
```
Open http://localhost:8000 → email-code login → `/admin` (officers) or `/member`.
With `DEV_PRINT_LOGIN_CODES=true` codes are printed in the server log instead of emailed (dev only).
