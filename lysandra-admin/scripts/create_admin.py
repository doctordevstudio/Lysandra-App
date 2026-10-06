"""
One-off CLI to create (or reset the password of) an admin account.
Run from the project root: python -m scripts.create_admin
"""
import getpass
import sys

sys.path.insert(0, ".")

from app.config import settings
from app.firebase_client import init_firebase, ref
from app.security import hash_password


def main():
    settings.validate()
    init_firebase()
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password: ").strip()
    confirm = getpass.getpass("Confirm password: ").strip()
    if password != confirm:
        print("Passwords don't match.")
        return
    if len(password) < 10:
        print("Use at least 10 characters.")
        return
    ref(f"/admin_auth/users/{username}").set({"password_hash": hash_password(password)})
    print(f"Admin user '{username}' created/updated.")


if __name__ == "__main__":
    main()
