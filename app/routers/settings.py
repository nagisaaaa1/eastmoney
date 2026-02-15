"""
Settings endpoints.
"""
import os
from fastapi import APIRouter, HTTPException

from app.models.settings import SettingsUpdate, NotificationSettingsUpdate, NotificationSettingsResponse, TestEmailRequest
from app.core.utils import load_env_file, save_env_file, mask_api_key

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("")
async def get_settings():
    """Get current settings (with masked API keys)."""
    env = load_env_file()

    return {
        "llm_provider": env.get("LLM_PROVIDER", "gemini"),
        "data_source_provider": env.get("DATA_SOURCE_PROVIDER", "hybrid"),
        "gemini_api_key_masked": mask_api_key(env.get("GEMINI_API_KEY", "")),
        "openai_api_key_masked": mask_api_key(env.get("OPENAI_API_KEY", "")),
        "openai_base_url": env.get("OPENAI_BASE_URL", ""),
        "openai_model": env.get("OPENAI_MODEL", ""),
        "tavily_api_key_masked": mask_api_key(env.get("TAVILY_API_KEY", ""))
    }


@router.post("")
async def update_settings(settings: SettingsUpdate):
    """Update application settings."""
    updates = {}
    if settings.llm_provider:
        updates["LLM_PROVIDER"] = settings.llm_provider
    if settings.gemini_api_key:
        updates["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.openai_api_key:
        updates["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_base_url is not None:
        updates["OPENAI_BASE_URL"] = settings.openai_base_url
    if settings.openai_model is not None:
        updates["OPENAI_MODEL"] = settings.openai_model
    if settings.tavily_api_key:
        updates["TAVILY_API_KEY"] = settings.tavily_api_key

    save_env_file(updates)

    # Update runtime env
    for k, v in updates.items():
        if v is not None:
            os.environ[k] = v

    return {"status": "success"}


# ============ Notification Settings ============

@router.get("/notifications", response_model=NotificationSettingsResponse)
async def get_notification_settings():
    """Get current notification/push settings."""
    env = load_env_file()
    
    return NotificationSettingsResponse(
        email_enabled=env.get("EMAIL_ENABLED", "").lower() == "true",
        smtp_host=env.get("SMTP_HOST", ""),
        smtp_port=int(env.get("SMTP_PORT", "587")),
        smtp_user=env.get("SMTP_USER", ""),
        smtp_password_masked=mask_api_key(env.get("SMTP_PASSWORD", "")),
        smtp_from_email=env.get("SMTP_FROM_EMAIL", ""),
        smtp_use_tls=env.get("SMTP_USE_TLS", "true").lower() == "true",
        recipient_email=env.get("NOTIFICATION_RECIPIENT_EMAIL", ""),
        notify_on_report=env.get("NOTIFY_ON_REPORT", "true").lower() == "true",
        notify_on_alert=env.get("NOTIFY_ON_ALERT", "true").lower() == "true",
        notify_daily_summary=env.get("NOTIFY_DAILY_SUMMARY", "").lower() == "true",
        quiet_hours_enabled=env.get("QUIET_HOURS_ENABLED", "").lower() == "true",
        quiet_hours_start=env.get("QUIET_HOURS_START", "22:00"),
        quiet_hours_end=env.get("QUIET_HOURS_END", "08:00"),
        daily_summary_time=env.get("DAILY_SUMMARY_TIME", "18:00"),
    )


@router.post("/notifications")
async def update_notification_settings(settings: NotificationSettingsUpdate):
    """Update notification/push settings."""
    updates = {}
    
    if settings.email_enabled is not None:
        updates["EMAIL_ENABLED"] = "true" if settings.email_enabled else "false"
    if settings.smtp_host is not None:
        updates["SMTP_HOST"] = settings.smtp_host
    if settings.smtp_port is not None:
        updates["SMTP_PORT"] = str(settings.smtp_port)
    if settings.smtp_user is not None:
        updates["SMTP_USER"] = settings.smtp_user
    if settings.smtp_password is not None:
        updates["SMTP_PASSWORD"] = settings.smtp_password
    if settings.smtp_from_email is not None:
        updates["SMTP_FROM_EMAIL"] = settings.smtp_from_email
    if settings.smtp_use_tls is not None:
        updates["SMTP_USE_TLS"] = "true" if settings.smtp_use_tls else "false"
    if settings.recipient_email is not None:
        updates["NOTIFICATION_RECIPIENT_EMAIL"] = settings.recipient_email
    if settings.notify_on_report is not None:
        updates["NOTIFY_ON_REPORT"] = "true" if settings.notify_on_report else "false"
    if settings.notify_on_alert is not None:
        updates["NOTIFY_ON_ALERT"] = "true" if settings.notify_on_alert else "false"
    if settings.notify_daily_summary is not None:
        updates["NOTIFY_DAILY_SUMMARY"] = "true" if settings.notify_daily_summary else "false"
    if settings.quiet_hours_enabled is not None:
        updates["QUIET_HOURS_ENABLED"] = "true" if settings.quiet_hours_enabled else "false"
    if settings.quiet_hours_start is not None:
        updates["QUIET_HOURS_START"] = settings.quiet_hours_start
    if settings.quiet_hours_end is not None:
        updates["QUIET_HOURS_END"] = settings.quiet_hours_end
    if settings.daily_summary_time is not None:
        updates["DAILY_SUMMARY_TIME"] = settings.daily_summary_time
    
    save_env_file(updates)
    
    # Update runtime env
    for k, v in updates.items():
        if v is not None:
            os.environ[k] = v
    
    return {"status": "success"}


@router.post("/notifications/test")
async def send_test_email(request: TestEmailRequest):
    """Send a test email to verify SMTP configuration."""
    from src.services.email_service import EmailService
    
    env = load_env_file()
    
    # Check if email is configured
    smtp_host = env.get("SMTP_HOST", "")
    if not smtp_host:
        raise HTTPException(status_code=400, detail="SMTP not configured. Please save SMTP settings first.")
    
    email_service = EmailService()
    recipient = request.recipient or env.get("NOTIFICATION_RECIPIENT_EMAIL", "")
    
    if not recipient:
        raise HTTPException(status_code=400, detail="No recipient email specified.")
    
    try:
        success = await email_service.send_test_email(recipient)
        if success:
            return {"status": "success", "message": f"Test email sent to {recipient}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send test email")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email error: {str(e)}")
