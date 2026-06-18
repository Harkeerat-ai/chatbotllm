"""
services.py — re-export facade for all business-logic modules.

All services are now defined in domain-specific modules under app/:
  ollama_client.py    OllamaClient (chat + embeddings)
  rag_service.py      RAGService (retrieval + answer generation)
  tracking_service.py TrackingService (order/shipment tracking)
  ingestion_service.py IngestionService (PDF / text / FAQ ingestion)
  crawler_service.py  CrawlerService (website crawler)
  auth_service.py     AuthService (admin auth)
  analytics_service.py AnalyticsService (event logging + summary)
  brand_service.py    BrandService (brand CRUD)
"""

from app.ollama_client import ollama  # noqa: F401
from app.rag_service import rag_service  # noqa: F401
from app.tracking_service import tracking_service  # noqa: F401
from app.ingestion_service import ingestion_service  # noqa: F401
from app.crawler_service import crawler_service  # noqa: F401
from app.auth_service import auth_service  # noqa: F401
from app.analytics_service import AnalyticsService, analytics_service  # noqa: F401
from app.brand_service import brand_service  # noqa: F401
from app.seed_service import seed_knowledge  # noqa: F401
