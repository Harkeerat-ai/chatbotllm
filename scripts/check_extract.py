import sys
sys.path.insert(0, '.')
from app.tracking_service import tracking_service
print(tracking_service.extract_lookup_value_with_type('where is my order trk-kalp-1001'))
print(tracking_service.extract_lookup_value_with_type('where is TRK-KALP-1001'))
print(tracking_service.extract_lookup_value_with_type('tracking number is TRK-KALP-1001'))
print(tracking_service.extract_lookup_value_with_type('where is my order KALP-1001'))
