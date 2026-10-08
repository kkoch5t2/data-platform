"""Use the snapshot's own JST date for time-dependent content invariants."""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
def snapshot_date(generated_at,now=None):
    value=datetime.fromisoformat(generated_at.replace('Z','+00:00'))
    if value.tzinfo is None: raise ValueError('snapshot timestamp has no timezone')
    if value>(now or datetime.now(timezone.utc))+timedelta(minutes=10):
        raise ValueError('snapshot timestamp is in the future')
    return value.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat()
