"""
Search implementation for NASA Earthdata using earthaccess.
"""

from aer.search_earthaccess.core import EarthAccessSearchPlugin, NoSpatialMetadataError

__all__ = ["EarthAccessSearchPlugin", "NoSpatialMetadataError"]
