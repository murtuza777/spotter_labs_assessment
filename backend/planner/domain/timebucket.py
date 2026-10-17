"""Which forecast hour applies to a moment in time.

Open-Meteo stamps gusts, rain, showers and snowfall at the END of the hour they cover
("preceding hour" max/sum). A truck passing at 14:20 is inside 14:00-15:00, whose values are
stamped 15:00, so we round the ETA up to the next whole hour.
"""

from datetime import UTC, datetime, timedelta


def forecast_hour_for(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    utc = moment.astimezone(UTC)
    floor = utc.replace(minute=0, second=0, microsecond=0)
    return floor if floor == utc else floor + timedelta(hours=1)
