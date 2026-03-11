from fastapi import APIRouter, Request

from app.schemas.auth import SignUpRequest, SignInRequest
from app.services.auth import sign_up, sign_in, get_profile, get_user_id_from_token

router = APIRouter()


@router.post("/signup")
async def signup(req: SignUpRequest):
    return await sign_up(req.email, req.password, req.display_name)


@router.post("/signin")
async def signin(req: SignInRequest):
    return await sign_in(req.email, req.password)


@router.get("/profile")
async def profile(request: Request):
    user_id = get_user_id_from_token(request)
    return await get_profile(user_id)
