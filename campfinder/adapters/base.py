"""The normalized format every adapter produces (PLAN.md §3, §4).

Adding a new booking system means writing one module that yields these
objects; storage, search and the UI never see source-specific data.
"""
from dataclasses import dataclass, field


class AdapterDisabled(Exception):
    """Raised when an adapter is switched off by configuration."""


class SchemaError(Exception):
    """The source returned data in a shape we don't recognise."""


@dataclass
class Agency:
    name: str
    booking_system: str
    website: str = ""


@dataclass
class Campsite:
    source_id: str
    name: str = ""
    loop: str = ""
    type: str = "tent"  # one of db.SITE_TYPES
    max_rv_length_ft: int | None = None
    max_people: int | None = None
    hookups: dict = field(default_factory=dict)  # electric_amps, water, sewer
    ada: bool = False
    pets: bool | None = None  # None = unknown
    price_per_night: float | None = None
    attributes: dict = field(default_factory=dict)


@dataclass
class Campground:
    source: str
    source_id: str
    name: str
    agency: Agency
    lat: float | None = None
    lng: float | None = None
    state: str = "CO"
    elevation_ft: int | None = None
    description: str = ""
    season_open: str | None = None
    season_close: str | None = None
    booking_url: str = ""
    booking_window_days: int | None = None
    reservable: bool = True
    amenities: list = field(default_factory=list)
    photos: list = field(default_factory=list)  # [{"url":..., "title":...}]
    extra: dict = field(default_factory=dict)  # source-specific details (verified, booking_id...)
    campsites: list[Campsite] = field(default_factory=list)


# Availability from an adapter: {campsite source_id: {"YYYY-MM-DD": status}}
SiteAvailability = dict[str, dict[str, str]]
