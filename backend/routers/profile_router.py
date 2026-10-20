"""The authenticated user's profile; identity is created by OAuth."""

from fastapi import APIRouter, Response, status

from core.security import REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME
from core.transaction import transaction
from routers.dependencies import UserDataServiceDep
from schemas.common import JsonObjectInput
from schemas.user import OnboardingInput, UserRead, UserUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserRead)
async def get_profile(service: UserDataServiceDep):
    return service.user


@router.patch("", response_model=UserRead)
@transaction
async def update_profile(payload: UserUpdate, service: UserDataServiceDep):
    return await service.update_profile(payload)


@router.patch("/personal-info", response_model=UserRead)
@transaction
async def merge_personal_info(payload: JsonObjectInput, service: UserDataServiceDep):
    """Merge top-level groups; replace the entire value of each supplied group."""
    return await service.merge_personal_info(payload.root)


@router.post("/onboarding", response_model=UserRead)
@transaction
async def complete_onboarding(payload: OnboardingInput, service: UserDataServiceDep):
    """Save profile, optional initial measurement and confirmed goal atomically."""
    return await service.onboard(payload)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
@transaction
async def delete_profile(service: UserDataServiceDep) -> Response:
    """Deactivate the account and revoke all refresh sessions; retain history."""
    await service.delete_profile()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    for cookie in (REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME):
        response.delete_cookie(cookie, path="/")
    return response
