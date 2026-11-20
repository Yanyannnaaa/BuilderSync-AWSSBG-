"""Check your email provider setup:  python -m app.send_test_email you@example.com"""
import sys

from app.config import get_settings
from app.services.email_service import send_email


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    s = get_settings()
    print(f"Provider={s.email_provider} from={s.email_from} region={s.aws_region}")
    try:
        send_email(argv[0], "BuilderSync test email", "<p>It works! 🎉</p>", "It works!")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {e}")
        return 2
    print("Sent. Check the inbox (and spam).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
