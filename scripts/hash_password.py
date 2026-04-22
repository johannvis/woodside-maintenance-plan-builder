#!/usr/bin/env python3
"""Generate a bcrypt hash for use in .streamlit/secrets.toml authentication config.

Usage:
    python scripts/hash_password.py
    python scripts/hash_password.py mypassword
"""

import sys


def hash_password(plaintext: str) -> str:
    try:
        import bcrypt
        hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8")
    except ImportError:
        pass

    try:
        import streamlit_authenticator as stauth
        return stauth.Hasher([plaintext]).generate()[0]
    except ImportError:
        pass

    raise RuntimeError(
        "Neither bcrypt nor streamlit-authenticator is installed. "
        "Run: pip install bcrypt"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        import getpass
        password = getpass.getpass("Enter password to hash: ")

    hashed = hash_password(password)
    print(f"\nBcrypt hash:\n  {hashed}")
    print("\nAdd to .streamlit/secrets.toml:")
    print(f'  password = "{hashed}"')
