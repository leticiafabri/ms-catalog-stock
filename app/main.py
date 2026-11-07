import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_session
from app.models import Product, Reservation
from app.schemas import (
    AvailabilityRead,
    HealthRead,
    ProductCreate,
    ProductRead,
    ReservationCreate,
    ReservationRead,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Convenient for this teaching project. Use migrations for a production rollout.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="MS Catalog Stock",
    description="Product catalog and stock validation for the MyTracker team project.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthRead, tags=["operations"])
def health(session: Session = Depends(get_session)) -> HealthRead:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return HealthRead(
        status="UP",
        database="connected",
        pod=os.getenv("HOSTNAME", "local"),
    )


@app.get("/instance", tags=["operations"])
def instance() -> dict[str, str]:
    return {"service": "ms-catalog-stock", "pod": os.getenv("HOSTNAME", "local")}


@app.post(
    "/api/catalog/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    tags=["products"],
)
def create_product(
    payload: ProductCreate, session: Session = Depends(get_session)
) -> Product:
    product = Product(**payload.model_dump())
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A product with this SKU already exists",
        ) from exc
    session.refresh(product)
    return product


@app.get("/api/catalog/products", response_model=list[ProductRead], tags=["products"])
def list_products(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[Product]:
    statement = select(Product).where(Product.active.is_(True)).offset(offset).limit(limit)
    return list(session.scalars(statement))


@app.get(
    "/api/catalog/products/{product_id}",
    response_model=ProductRead,
    tags=["products"],
)
def get_product(product_id: int, session: Session = Depends(get_session)) -> Product:
    product = session.get(Product, product_id)
    if product is None or not product.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@app.get(
    "/api/catalog/products/{product_id}/availability",
    response_model=AvailabilityRead,
    tags=["stock"],
)
def check_availability(
    product_id: int,
    quantity: int = Query(default=1, gt=0),
    session: Session = Depends(get_session),
) -> AvailabilityRead:
    product = session.get(Product, product_id)
    if product is None or not product.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return AvailabilityRead(
        product_id=product.id,
        sku=product.sku,
        requested_quantity=quantity,
        available_quantity=product.available_quantity,
        available=product.available_quantity >= quantity,
    )


@app.post(
    "/api/catalog/products/{product_id}/reservations",
    response_model=ReservationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["stock"],
)
def reserve_stock(
    product_id: int,
    payload: ReservationCreate,
    session: Session = Depends(get_session),
) -> Reservation:
    product = session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None or not product.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Locking the product first serializes reservations for it and makes this
    # idempotency check reliable when the same order is submitted concurrently.
    existing = session.scalar(
        select(Reservation).where(
            Reservation.order_id == payload.order_id,
            Reservation.product_id == product_id,
        )
    )
    if existing is not None:
        if existing.quantity != payload.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This order already has a different reservation for the product",
            )
        return existing

    if product.available_quantity < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insufficient stock",
        )

    product.available_quantity -= payload.quantity
    reservation = Reservation(
        order_id=payload.order_id,
        product_id=product_id,
        quantity=payload.quantity,
    )
    session.add(reservation)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A reservation for this order and product already exists",
        ) from exc
    session.refresh(reservation)
    return reservation


@app.get(
    "/api/catalog/reservations/{order_id}",
    response_model=list[ReservationRead],
    tags=["stock"],
)
def list_order_reservations(
    order_id: str, session: Session = Depends(get_session)
) -> list[Reservation]:
    statement = (
        select(Reservation)
        .where(Reservation.order_id == order_id)
        .order_by(Reservation.id)
    )
    return list(session.scalars(statement))
