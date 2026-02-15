"""
Settings-related Pydantic models.
"""
from typing import Optional, List
from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    """Update application settings."""
    llm_provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    tavily_api_key: Optional[str] = None


class NotificationSettingsUpdate(BaseModel):
    """Update notification/push settings."""
    # Master switch
    email_enabled: Optional[bool] = None
    
    # SMTP Configuration
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    recipient_email: Optional[str] = None
    
    # Feature toggles - what triggers notifications
    notify_on_report: Optional[bool] = None
    notify_on_alert: Optional[bool] = None
    notify_daily_summary: Optional[bool] = None
    
    # Timing settings
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None  # "HH:MM" format
    quiet_hours_end: Optional[str] = None    # "HH:MM" format
    daily_summary_time: Optional[str] = None  # "HH:MM" format


class NotificationSettingsResponse(BaseModel):
    """Response model for notification settings."""
    email_enabled: bool = False
    
    # SMTP (passwords masked)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password_masked: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    recipient_email: str = ""
    
    # Feature toggles
    notify_on_report: bool = True
    notify_on_alert: bool = True
    notify_daily_summary: bool = False
    
    # Timing
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"
    daily_summary_time: str = "18:00"


class TestEmailRequest(BaseModel):
    """Request to send a test email."""
    recipient: Optional[str] = None  # Optional override


class ModelListRequest(BaseModel):
    """Request to list available LLM models."""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    provider: str = "openai"


class GenerateRequest(BaseModel):
    """Request to generate a report."""
    fund_code: Optional[str] = None
    force: bool = False


class CommodityAnalyzeRequest(BaseModel):
    """Request to analyze a commodity."""
    asset: str  # "gold" or "silver"
