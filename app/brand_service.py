"""
Brand service — CRUD for brands.
"""

from __future__ import annotations
import logging

from sqlalchemy.orm import Session

from app import models
from app.chroma_client import delete_collection
from app.config import get_settings
from app.utils import slugify

logger = logging.getLogger(__name__)
settings = get_settings()


class BrandService:
    def get_or_create(self, db: Session, slug: str) -> models.Brand:
        brand = db.query(models.Brand).filter_by(slug=slug).first()
        if not brand:
            brand = models.Brand(slug=slug, name=slug.replace("-", " ").title())
            db.add(brand)
            db.commit()
            db.refresh(brand)
        return brand

    def create(self, db: Session, slug: str, name: str, description: str = "") -> models.Brand:
        brand = models.Brand(slug=slugify(slug), name=name, description=description)
        db.add(brand)
        db.commit()
        db.refresh(brand)
        return brand

    def list_all(self, db: Session) -> list[models.Brand]:
        return db.query(models.Brand).order_by(models.Brand.created_at).all()

    def delete(self, db: Session, brand: models.Brand) -> None:
        delete_collection(brand.slug)
        db.delete(brand)
        db.commit()


brand_service = BrandService()
