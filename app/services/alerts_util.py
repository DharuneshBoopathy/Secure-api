from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Alert
from app.security import utc_now


def recent_duplicate(
    db: Session,
    *,
    org_id: int,
    alert_type: str,
    method: str | None,
    path: str | None,
    within_hours: float = 6,
) -> bool:
    since = utc_now() - timedelta(hours=within_hours)
    q = db.query(Alert).filter(
        Alert.org_id == org_id,
        Alert.alert_type == alert_type,
        Alert.created_at >= since,
        Alert.acknowledged.is_(False),
    )
    if method:
        q = q.filter(Alert.method == method)
    if path:
        q = q.filter(Alert.path == path)
    return q.first() is not None
