"""One adapter per booking system. Availability adapters are registered by source name."""
from . import recgov

# source -> fetch_month(source_campground_id, month_start) -> (http_status, SiteAvailability)
AVAILABILITY_ADAPTERS = {
    recgov.SOURCE: recgov.fetch_month,
}
