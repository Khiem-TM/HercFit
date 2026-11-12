"""Hồ sơ của người dùng đã xác thực; danh tính được tạo bởi OAuth."""

from fastapi import APIRouter, Response, status

from api.dependencies import UserDataServiceDep
from core.idempotency import IdempotentRoute
from core.security import REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME
from core.transaction import transaction
from domains.identity.schemas.user import OnboardingInput, UserRead, UserUpdate
from domains.shared.schemas.common import JsonObjectInput

router = APIRouter(route_class=IdempotentRoute, prefix="/profile", tags=["profile"])


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
    """Gộp các nhóm cấp cao nhất; thay toàn bộ giá trị của từng nhóm được truyền."""
    return await service.merge_personal_info(payload.root)


@router.post("/onboarding", response_model=UserRead)
@transaction
async def complete_onboarding(payload: OnboardingInput, service: UserDataServiceDep):
    """Lưu nguyên tử hồ sơ, số đo ban đầu (tuỳ chọn) và mục tiêu đã xác nhận."""
    return await service.onboard(payload)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
@transaction
async def delete_profile(service: UserDataServiceDep) -> Response:
    """Vô hiệu hoá tài khoản và thu hồi mọi phiên refresh; giữ lại lịch sử."""
    await service.delete_profile()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    for cookie in (REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME):
        response.delete_cookie(cookie, path="/")
    return response
