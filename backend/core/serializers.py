"""
Serialization helpers for API responses and storage.
"""

from datetime import datetime, date, time, timedelta

import numpy as np


def sanitize_for_json(obj):
    """Recursively convert numpy / neo4j types to python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_for_json(obj.tolist())

    # Neo4j temporal / spatial types
    try:
        import neo4j.time as nt

        if isinstance(obj, (nt.DateTime, nt.Date, nt.Time)):
            return obj.iso_format()
        if isinstance(obj, nt.Duration):
            return str(obj)
    except ImportError:
        pass

    # Standard-library temporal types
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return str(obj)

    return obj
