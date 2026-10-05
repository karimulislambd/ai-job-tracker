from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep, rate_limit, verify_origin
from app.core.config import Settings
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.auth import AuthService, IssuedTokens
from app.services.demo import DemoService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, issued: IssuedTokens, settings: Settings) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=issued.refresh_token,
        expires=issued.refresh_expires_at,
        path=settings.refresh_cookie_path,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _token_response(issued: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=issued.access.token,
        expires_at=issued.access.expires_at,
        user=UserOut.model_validate(issued.user),
    )


def _refresh_cookie(request: Request, settings: SettingsDep) -> str | None:
    return request.cookies.get(settings.refresh_cookie_name)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth:register"))],
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    service = AuthService(session, settings)
    user = await service.register(body.email, body.password, body.full_name)
    issued, _ = await service.issue_tokens(user, user_agent=request.headers.get("user-agent"))
    await session.commit()
    _set_refresh_cookie(response, issued, settings)
    return _token_response(issued)


@router.post(
    "/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("auth:login"))]
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    issued = await AuthService(session, settings).login(
        body.email, body.password, request.headers.get("user-agent")
    )
    _set_refresh_cookie(response, issued, settings)
    return _token_response(issued)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(verify_origin), Depends(rate_limit("auth:refresh", multiplier=6))],
    summary="Rotate the refresh-token cookie and get a new access token",
)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    raw: Annotated[str | None, Depends(_refresh_cookie)],
) -> TokenResponse:
    issued = await AuthService(session, settings).refresh(raw, request.headers.get("user-agent"))
    _set_refresh_cookie(response, issued, settings)
    return _token_response(issued)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_origin)],
    summary="Revoke the refresh-token family and clear the cookie",
)
async def logout(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    raw: Annotated[str | None, Depends(_refresh_cookie)],
) -> Response:
    await AuthService(session, settings).logout(raw)
    _clear_refresh_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/demo",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth:demo"))],
    summary="Log in as a fresh, isolated demo user (cloned from seed data, expires in 24h)",
)
async def demo_login(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    user = await DemoService(session, settings).create_demo_user()
    issued, _ = await AuthService(session, settings).issue_tokens(
        user, user_agent=request.headers.get("user-agent")
    )
    await session.commit()
    _set_refresh_cookie(response, issued, settings)
    return _token_response(issued)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
