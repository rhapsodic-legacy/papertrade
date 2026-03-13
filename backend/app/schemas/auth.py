from pydantic import BaseModel, EmailStr


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr


class UpdatePasswordRequest(BaseModel):
    access_token: str
    new_password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    email: str


class ProfileResponse(BaseModel):
    id: str
    display_name: str
    cash_balance: float
