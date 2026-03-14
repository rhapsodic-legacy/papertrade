from fastapi import HTTPException, Request
from app.services.supabase_client import get_supabase_client, get_supabase_admin


def get_user_id_from_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.split(" ")[1]
    db = get_supabase_client()

    try:
        user_resp = db.auth.get_user(token)
        return user_resp.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def sign_up(email: str, password: str, display_name: str | None = None) -> dict:
    db = get_supabase_client()
    try:
        resp = db.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {"display_name": display_name or email.split("@")[0]}
                },
            }
        )
        session = resp.session
        if not session:
            return {"message": "Check your email for a confirmation link", "user_id": resp.user.id}

        return {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "user_id": resp.user.id,
            "email": email,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def sign_in(email: str, password: str) -> dict:
    db = get_supabase_client()
    try:
        resp = db.auth.sign_in_with_password({"email": email, "password": password})
        return {
            "access_token": resp.session.access_token,
            "refresh_token": resp.session.refresh_token,
            "user_id": resp.user.id,
            "email": email,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid email or password")


async def reset_password(email: str, redirect_url: str) -> dict:
    db = get_supabase_client()
    try:
        db.auth.reset_password_email(email, {"redirect_to": redirect_url})
        return {"message": "If an account exists with that email, a reset link has been sent"}
    except Exception:
        # Return same message to avoid leaking whether email exists
        return {"message": "If an account exists with that email, a reset link has been sent"}


async def update_password(access_token: str, refresh_token: str, new_password: str) -> dict:
    db = get_supabase_client()
    try:
        # Establish a session with the recovery tokens so update_user works
        db.auth.set_session(access_token, refresh_token)
        db.auth.update_user({"password": new_password})
        return {"message": "Password updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def get_profile(user_id: str) -> dict:
    db = get_supabase_admin()
    resp = db.table("profiles").select("*").eq("id", user_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return resp.data
