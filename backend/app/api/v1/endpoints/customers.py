from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.customer import Customer, Establishment
from app.models.user import User
from app.repositories.crud import CrudRepository
from app.schemas.customer import (
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    EstablishmentCreate,
    EstablishmentRead,
    EstablishmentUpdate,
)
from app.security.dependencies import get_current_user

router = APIRouter()
customers = CrudRepository(Customer)
establishments = CrudRepository(Establishment)


@router.get("/", response_model=list[CustomerRead])
def list_customers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return customers.list_by_tenant(db, current_user.tenant_id)


@router.post("/", response_model=CustomerRead, status_code=201)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.model_dump()
    data["tenant_id"] = current_user.tenant_id
    return customers.create(db, data)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = customers.update_for_tenant(db, current_user.tenant_id, customer_id, payload.model_dump(exclude_unset=True))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.post("/establishments", response_model=EstablishmentRead, status_code=201)
def create_establishment(
    payload: EstablishmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = db.scalar(select(Customer).where(Customer.id == payload.customer_id, Customer.tenant_id == current_user.tenant_id))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    data = payload.model_dump()
    data["tenant_id"] = current_user.tenant_id
    return establishments.create(db, data)


@router.patch("/establishments/{establishment_id}", response_model=EstablishmentRead)
def update_establishment(
    establishment_id: UUID,
    payload: EstablishmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    establishment = establishments.update_for_tenant(
        db,
        current_user.tenant_id,
        establishment_id,
        payload.model_dump(exclude_unset=True),
    )
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establishment not found")
    return establishment
