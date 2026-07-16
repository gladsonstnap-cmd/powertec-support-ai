from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


class CrudRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    def list_by_tenant(self, db: Session, tenant_id) -> list[ModelT]:
        return list(db.scalars(select(self.model).where(self.model.tenant_id == tenant_id)))

    def create(self, db: Session, payload: dict) -> ModelT:
        instance = self.model(**payload)
        db.add(instance)
        db.commit()
        db.refresh(instance)
        return instance

    def get_for_tenant(self, db: Session, tenant_id, item_id) -> ModelT | None:
        return db.scalar(select(self.model).where(self.model.tenant_id == tenant_id, self.model.id == item_id))

    def update_for_tenant(self, db: Session, tenant_id, item_id, payload: dict) -> ModelT | None:
        instance = self.get_for_tenant(db, tenant_id, item_id)
        if instance is None:
            return None
        for key, value in payload.items():
            if key != "tenant_id" and value is not None:
                setattr(instance, key, value)
        db.commit()
        db.refresh(instance)
        return instance
