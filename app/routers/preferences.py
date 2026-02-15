"""
User preferences endpoints.
"""
from typing import Dict
from fastapi import APIRouter, HTTPException, Depends

from app.models.auth import User
from app.core.dependencies import get_current_user
from src.storage.db import get_user_preferences, save_user_preferences
from src.storage.user_preferences import RISK_LEVEL_PRESETS, RiskLevel

router = APIRouter(prefix="/api/preferences", tags=["Preferences"])


@router.get("")
async def get_user_preferences_endpoint(current_user: User = Depends(get_current_user)):
    """Get user investment preferences."""
    try:
        prefs = get_user_preferences(user_id=current_user.id)

        if not prefs:
            # Return default moderate preferences
            default_prefs = RISK_LEVEL_PRESETS[RiskLevel.MODERATE].to_dict()
            return {
                "exists": False,
                "preferences": default_prefs
            }

        return {
            "exists": True,
            "preferences": prefs.get("preferences", {}),
            "updated_at": prefs.get("updated_at")
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def save_user_preferences_endpoint(
    preferences: Dict,
    current_user: User = Depends(get_current_user)
):
    """Save user investment preferences."""
    try:
        existing = get_user_preferences(user_id=current_user.id) or {}
        merged_preferences = {
            **(existing.get("preferences") or {}),
            **(preferences or {}),
        }
        save_user_preferences(user_id=current_user.id, preferences=merged_preferences)

        return {
            "success": True,
            "message": "Investment preferences saved successfully"
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/presets")
async def get_preference_presets():
    """Get predefined risk level presets."""
    try:
        presets = {}
        for risk_level in RiskLevel:
            presets[risk_level.value] = RISK_LEVEL_PRESETS[risk_level].to_dict()

        return {"presets": presets}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
