import os

from fastapi import APIRouter, Request

from app.schemas.auth import SignUpRequest, SignInRequest, ResetPasswordRequest, UpdatePasswordRequest, RefreshRequest
from app.services.auth import sign_up, sign_in, get_profile, get_user_id_from_token, reset_password, update_password, refresh_session

router = APIRouter()


@router.post("/signup")
async def signup(req: SignUpRequest):
    return await sign_up(req.email, req.password, req.display_name)


@router.post("/signin")
async def signin(req: SignInRequest):
    return await sign_in(req.email, req.password)


@router.post("/reset-password")
async def request_reset(req: ResetPasswordRequest):
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    redirect_url = f"{frontend_url}/auth/reset"
    return await reset_password(req.email, redirect_url)


@router.post("/update-password")
async def update_pwd(req: UpdatePasswordRequest):
    return await update_password(req.access_token, req.refresh_token, req.new_password)


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    return await refresh_session(req.refresh_token)


@router.get("/profile")
async def profile(request: Request):
    user_id = get_user_id_from_token(request)
    return await get_profile(user_id)
