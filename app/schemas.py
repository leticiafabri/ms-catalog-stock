from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    available_quantity: int = Field(default=0, ge=0)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: str
    price: Decimal
    available_quantity: int
    active: bool
    created_at: datetime


class AvailabilityRead(BaseModel):
    product_id: int
    sku: str
    requested_quantity: int
    available_quantity: int
    available: bool


class ReservationCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0)


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: str
    product_id: int
    quantity: int
    status: str
    created_at: datetime


class HealthRead(BaseModel):
    status: str
    database: str
    pod: str
