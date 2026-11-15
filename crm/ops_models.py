"""
Pydantic models for Ops (Incidents & Alerts) API
Phase 1: Incidents & Alerts MVP
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ============ INCIDENTS ============

class Incident(BaseModel):
    """Incident model"""
    id: str
    type: str
    severity: str
    status: str
    scope: str
    metric: str
    baseline_value: Optional[float] = None
    current_value: float
    delta_value: Optional[float] = None
    delta_pct: Optional[float] = None
    period_from: datetime
    period_to: datetime
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    title: str
    description: Optional[str] = None
    owner_user_id: Optional[str] = None
    created_by: str = "rule"
    rule_id: Optional[str] = None
    dedupe_key: str
    ack_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None
    is_muted: bool = False
    mute_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IncidentEvent(BaseModel):
    """Incident event (timeline) model"""
    id: str
    incident_id: str
    event_type: str
    actor_user_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class IncidentListResponse(BaseModel):
    """Response for incident list"""
    incidents: List[Incident]
    total: int


class IncidentDetailResponse(BaseModel):
    """Response for incident detail"""
    incident: Incident
    events: List[IncidentEvent]


class IncidentAckRequest(BaseModel):
    """Request to acknowledge incident"""
    user_id: Optional[str] = None


class IncidentResolveRequest(BaseModel):
    """Request to resolve incident"""
    user_id: Optional[str] = None


class IncidentReopenRequest(BaseModel):
    """Request to reopen incident"""
    user_id: Optional[str] = None


class IncidentAssignRequest(BaseModel):
    """Request to assign incident"""
    owner_user_id: str
    user_id: Optional[str] = None


class IncidentMuteRequest(BaseModel):
    """Request to mute incident"""
    minutes: Optional[int] = None
    until: Optional[datetime] = None
    user_id: Optional[str] = None


class IncidentUnmuteRequest(BaseModel):
    """Request to unmute incident"""
    user_id: Optional[str] = None


class IncidentCommentRequest(BaseModel):
    """Request to add comment to incident"""
    text: str
    user_id: Optional[str] = None


# ============ ALERTS ============

class Alert(BaseModel):
    """Alert model"""
    id: str
    name: str
    metric: str
    severity: str
    scope: str
    condition: Dict[str, Any]
    time_window: Dict[str, Any]
    filters: Dict[str, Any] = Field(default_factory=dict)
    recipients: Dict[str, Any] = Field(default_factory=dict)
    cooldown_minutes: int = 15
    enabled: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlertCreateRequest(BaseModel):
    """Request to create alert"""
    name: str
    metric: str
    severity: str
    scope: str
    condition: Dict[str, Any]
    time_window: Dict[str, Any]
    filters: Dict[str, Any] = Field(default_factory=dict)
    recipients: Dict[str, Any] = Field(default_factory=dict)
    cooldown_minutes: int = 15
    enabled: bool = True


class AlertUpdateRequest(BaseModel):
    """Request to update alert"""
    name: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    time_window: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    recipients: Optional[Dict[str, Any]] = None
    cooldown_minutes: Optional[int] = None
    enabled: Optional[bool] = None


class AlertToggleRequest(BaseModel):
    """Request to toggle alert enabled status"""
    enabled: bool


class AlertListResponse(BaseModel):
    """Response for alert list"""
    alerts: List[Alert]


class AlertFire(BaseModel):
    """Alert fire model"""
    id: str
    alert_id: str
    fired_at: datetime
    context: Dict[str, Any]
    incident_id: Optional[str] = None
    delivered: bool = False
    delivered_at: Optional[datetime] = None
    delivery_errors: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============ HEALTH ============

class HealthResponse(BaseModel):
    """Health check response"""
    status: str  # "ok" | "degraded" | "error"
    database: bool
    metabase: bool
    cache: Optional[Dict[str, Any]] = None
    timestamp: datetime
