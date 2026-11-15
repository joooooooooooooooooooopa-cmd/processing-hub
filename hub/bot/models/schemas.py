from pydantic import BaseModel
from typing import Optional


class User(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    language_code: Optional[str] = None
    created_at: Optional[str] = None
    last_active: Optional[str] = None


class Subscription(BaseModel):
    id: Optional[int] = None
    user_id: int
    started_at: str
    expires_at: str
    payment_id: Optional[str] = None


class GlossaryTerm(BaseModel):
    term: str
    term_ru: str
    category: str
    definition: str
    example: Optional[str] = None
    related: Optional[list[str]] = None


class Country(BaseModel):
    code: str
    name: str
    name_ru: str
    region: str
    gambling: Optional[str] = None
    crypto: Optional[str] = None
    forex: Optional[str] = None
    adult: Optional[str] = None
    nutra: Optional[str] = None
    banking_system: Optional[str] = None
    risk_level: Optional[str] = None
    popular_acquirers: Optional[list[str]] = None


class Acquirer(BaseModel):
    name: str
    type: Optional[str] = None
    verticals: Optional[list[str]] = None
    regions: Optional[list[str]] = None
    risk_level: Optional[str] = None
    min_volume: Optional[str] = None
    rolling_reserve: Optional[str] = None
    chargeback_threshold: Optional[str] = None
    settlement: Optional[str] = None
    rating: Optional[float] = None
    pros: Optional[list[str]] = None
    cons: Optional[list[str]] = None
    description: Optional[str] = None


class Platform(BaseModel):
    name: str
    type: str
    website: Optional[str] = None
    registration_country: Optional[str] = None
    services: Optional[list[str]] = None
    risk_level: Optional[str] = None
    notes: Optional[str] = None


class CalendarMonth(BaseModel):
    month: int
    name: str
    verticals: Optional[dict] = None


class TrafficVertical(BaseModel):
    vertical: str
    name_ru: str
    top_geos: Optional[list[str]] = None
    traffic_sources: Optional[list[str]] = None
    avg_check: Optional[str] = None
    notes: Optional[str] = None


class NewsItem(BaseModel):
    title: str
    source: str
    date: Optional[str] = None
    summary: Optional[str] = None
    url: Optional[str] = None


class BinResult(BaseModel):
    bin: str
    bank: Optional[str] = None
    country: Optional[str] = None
    card_type: Optional[str] = None
    brand: Optional[str] = None
    prepaid: Optional[bool] = None
