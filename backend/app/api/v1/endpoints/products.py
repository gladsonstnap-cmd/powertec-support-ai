from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product, ProductVersion
from app.models.user import User
from app.repositories.crud import CrudRepository
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate, ProductVersionCreate, ProductVersionRead
from app.security.dependencies import get_current_user

router = APIRouter()
products = CrudRepository(Product)
versions = CrudRepository(ProductVersion)


@router.get("/", response_model=list[ProductRead])
def list_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return products.list_by_tenant(db, current_user.tenant_id)


@router.post("/", response_model=ProductRead, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = payload.model_dump()
    data["tenant_id"] = current_user.tenant_id
    return products.create(db, data)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = products.update_for_tenant(db, current_user.tenant_id, product_id, payload.model_dump(exclude_unset=True))
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("/versions", response_model=ProductVersionRead, status_code=201)
def create_product_version(
    payload: ProductVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.scalar(select(Product).where(Product.id == payload.product_id, Product.tenant_id == current_user.tenant_id))
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    data = payload.model_dump()
    data["tenant_id"] = current_user.tenant_id
    return versions.create(db, data)
