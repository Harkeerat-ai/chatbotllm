#!/usr/bin/env python3
"""Run seed.py with logging enabled to surface ingestion errors."""
import logging
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO)

import seed

if __name__ == '__main__':
    seed.seed()
