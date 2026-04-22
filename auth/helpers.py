"""Shared login wall helper for main and admin Streamlit apps.

Usage in app.py:
    from auth.helpers import render_login_wall
    render_login_wall()   # blocks if not authenticated

Usage in admin/app_admin.py:
    import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from auth.helpers import render_login_wall
    render_login_wall(section_key="auth_admin")

Secrets structure in .streamlit/secrets.toml (main app):
    [auth]
    cookie_name = "maint_plan_auth"
    cookie_key  = "<random 32-char string>"
    cookie_expiry_days = 30

    [auth.credentials.usernames.jvisser]
    name     = "Johann Visser"
    password = "$2b$12$..."   # bcrypt hash — use scripts/hash_password.py
    role     = "planner"

    [auth.credentials.usernames.demo]
    name     = "Demo User"
    password = "$2b$12$..."
    role     = "viewer"

Secrets structure for admin app (admin/.streamlit/secrets.toml):
    [auth_admin]
    cookie_name = "maint_admin_auth"
    cookie_key  = "<different 32-char string>"
    cookie_expiry_days = 30

    [auth_admin.credentials.usernames.jason]
    name     = "Jason (SME)"
    password = "$2b$12$..."
    role     = "admin"

If the secrets section is not configured, the login wall is skipped (dev mode).
"""

import streamlit as st


def render_login_wall(section_key: str = "auth") -> str | None:
    """
    Render a login wall. Returns the authenticated user's role, or None if auth is skipped.

    Blocks execution (st.stop()) if not authenticated.
    Must be called before any other page content is rendered.
    """
    # Check if auth secrets are configured
    try:
        auth_config = st.secrets.get(section_key)
    except Exception:
        auth_config = None

    if not auth_config:
        # Auth not configured — dev/demo mode, skip login wall
        return None

    try:
        import streamlit_authenticator as stauth
    except ImportError:
        st.warning(
            "⚠️ `streamlit-authenticator` not installed. "
            "Run `pip install streamlit-authenticator` to enable login."
        )
        return None

    # Build credentials dict from secrets
    cookie_name = auth_config.get("cookie_name", "maint_auth")
    cookie_key = auth_config.get("cookie_key", "default_key_change_me")
    cookie_expiry_days = int(auth_config.get("cookie_expiry_days", 30))

    raw_users = auth_config.get("credentials", {}).get("usernames", {})
    credentials = {
        "usernames": {
            username: {
                "name": info.get("name", username),
                "password": info.get("password", ""),
            }
            for username, info in raw_users.items()
        }
    }

    authenticator = stauth.Authenticate(
        credentials,
        cookie_name,
        cookie_key,
        cookie_expiry_days=cookie_expiry_days,
    )

    authenticator.login()

    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username", "")

    if auth_status is True:
        # Logged in — show logout in sidebar and return role
        with st.sidebar:
            st.markdown(f"**{st.session_state.get('name', username)}**")
            authenticator.logout("Logout", "sidebar")

        role = raw_users.get(username, {}).get("role", "viewer")
        st.session_state["auth_role"] = role
        return role

    elif auth_status is False:
        st.error("Incorrect username or password.")
        st.stop()

    else:
        # auth_status is None — not yet attempted
        st.stop()
