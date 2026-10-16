"""Centralized API router aggregating all domain CRUD routers."""

from fastapi import APIRouter

from routers.habit_router import router as habit_router
from routers.nutrition_router import router as nutrition_router
from routers.user_router import router as user_router
from routers.workout_router import router as workout_router

api_router = APIRouter()
api_router.include_router(user_router)
api_router.include_router(nutrition_router)
api_router.include_router(workout_router)
api_router.include_router(habit_router)

__all__ = ["api_router"]

