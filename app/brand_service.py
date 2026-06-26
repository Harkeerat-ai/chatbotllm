"""
Brand service — CRUD for brands.
"""

from __future__ import annotations
import json
import logging

from sqlalchemy.orm import Session

from app import models
from app.chroma_client import delete_collection
from app.config import get_settings
from app.schemas import WidgetConfig
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

    def create(self, db: Session, slug: str, name: str, description: str = "", language: str = "en") -> models.Brand:
        brand = models.Brand(slug=slugify(slug), name=name, description=description, language=language)
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

    def update(self, db: Session, brand: models.Brand, name: str | None = None, description: str | None = None, language: str | None = None) -> models.Brand:
        if name is not None:
            brand.name = name
        if description is not None:
            brand.description = description
        if language is not None:
            brand.language = language
        db.commit()
        db.refresh(brand)
        return brand

    def get_widget_config(self, db: Session, brand_slug: str) -> WidgetConfig:
        brand = db.query(models.Brand).filter_by(slug=brand_slug).first()
        if not brand:
            return WidgetConfig()
        try:
            data = json.loads(brand.widget_config_json) if brand.widget_config_json else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        return WidgetConfig(**data)

    def update_widget_config(self, db: Session, brand_slug: str, updates: dict) -> WidgetConfig:
        ALLOWED = {
            "title", "welcome_message", "accent_color", "bg_color",
            "logo_url", "width", "height", "position",
            "show_think_fast", "input_placeholder",
        }
        brand = db.query(models.Brand).filter_by(slug=brand_slug).first()
        if not brand:
            from fastapi import HTTPException
            raise HTTPException(404, "Brand not found")
        try:
            current = json.loads(brand.widget_config_json) if brand.widget_config_json else {}
        except (json.JSONDecodeError, TypeError):
            current = {}
        current.update({k: v for k, v in updates.items() if v is not None and k in ALLOWED})
        brand.widget_config_json = json.dumps(current)
        db.commit()
        return WidgetConfig(**current)


brand_service = BrandService()
