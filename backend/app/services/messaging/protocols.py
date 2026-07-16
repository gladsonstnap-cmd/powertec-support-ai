from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.messaging import ProtocolCounter


def generate_protocol(db: Session, tenant_id) -> str:
    year = datetime.now(UTC).year
    counter = db.scalar(
        select(ProtocolCounter)
        .where(ProtocolCounter.tenant_id == tenant_id, ProtocolCounter.year == year)
        .with_for_update()
    )
    if counter is None:
        counter = ProtocolCounter(tenant_id=tenant_id, year=year, next_value=1)
        db.add(counter)
        db.flush()
    value = counter.next_value
    counter.next_value += 1
    return f"PWT-{year}-{value:06d}"
