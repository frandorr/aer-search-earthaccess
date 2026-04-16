import hashlib
from datetime import datetime
from collections.abc import Mapping, Sequence
from typing import Any, cast, override

import earthaccess
import geopandas as gpd
from pandas import Series
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from structlog import get_logger

from aer.interfaces import SearchProvider
from aer.schemas import AssetSchema
from pandera.typing.geopandas import GeoDataFrame


logger = get_logger()


class NoSpatialMetadataError(Exception):
    """Raised when a UMM representation does not contain spatial metadata."""

    pass


def _parse_umm_polygon(umm: dict[str, Any]) -> Polygon:
    """Parse UMM (Unified Metadata Model) spatial extent into a Shapely Polygon.

    Tries to find GPolygons -> Boundary -> Points and constructs a Polygon.
    If none found, raises NoSpatialMetadataError.
    """
    spatial = umm.get("SpatialExtent", {})
    horiz = spatial.get("HorizontalSpatialDomain", {})
    geometry = horiz.get("Geometry", {})

    # Check for GPolygons
    if "GPolygons" in geometry:
        for p in geometry["GPolygons"]:
            boundary = p.get("Boundary", {})
            points = boundary.get("Points", [])
            if len(points) >= 3:
                coords = [(pt["Longitude"], pt["Latitude"]) for pt in points]
                return Polygon(coords)

    # Check for BoundingRectangles
    if "BoundingRectangles" in geometry:
        for rect in geometry["BoundingRectangles"]:
            min_x = rect.get("WestBoundingCoordinate")
            max_x = rect.get("EastBoundingCoordinate")
            min_y = rect.get("SouthBoundingCoordinate")
            max_y = rect.get("NorthBoundingCoordinate")
            if all(v is not None for v in (min_x, max_x, min_y, max_y)):
                return Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)])

    raise NoSpatialMetadataError("Could not find GPolygon or BoundingRectangle in UMM")


class EarthAccessSearchPlugin(SearchProvider, plugin_abstract=False):
    # EarthAccess theoretically supports all NASA collections, we use "*" as a wildcard.
    supported_collections: Sequence[str] = ["*"]

    @override
    def search(
        self,
        collections: Sequence[str],
        intersects: BaseGeometry | None = None,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
        search_params: Mapping[str, Any] | None = None,
    ) -> GeoDataFrame[AssetSchema]:
        """Search NASA Earthdata using earthaccess.

        Args:
            collections: List of dataset short names (e.g. ["VNP02IMG"]).
            intersects: Geometry to filter by. Converted to a bounding box for Earthaccess.
            time_range: Time range to filter by.
            search_params: Additional kwargs to pass directly to earthaccess.search_data.
        """
        if not collections:
            return self._empty_result()

        kwargs: dict[str, Any] = {"short_name": collections}

        if start_datetime and end_datetime:
            kwargs["temporal"] = (
                start_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                end_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            )

        if intersects is not None:
            # earthaccess expects bounding_box as (lower_left_lon, lower_left_lat, upper_right_lon, upper_right_lat)
            bounds = getattr(intersects, "bounds", None)
            if bounds is not None:
                kwargs["bounding_box"] = bounds

        if search_params:
            kwargs.update(search_params)

        try:
            granules = earthaccess.search_data(**kwargs)
        except Exception as e:
            logger.error("earthaccess search failed", error=str(e), **kwargs)
            return self._empty_result()

        if not granules:
            return self._empty_result()

        rows = []
        for g in granules:
            meta = g["meta"]
            umm = g["umm"]

            # The Granule UR or concept-id works as a unique identifier
            cid = meta.get("concept-id") or meta.get("native-id", "unknown")
            unique_id = hashlib.md5(cid.encode("utf-8")).hexdigest()

            # Collection short name
            coll_ref = umm.get("CollectionReference", {})
            collection_name = coll_ref.get("ShortName", collections[0])

            # Parse temporal
            temp_ext = umm.get("TemporalExtent", {})
            range_dt = temp_ext.get("RangeDateTime", {})
            start_str = range_dt.get("BeginningDateTime")
            end_str = range_dt.get("EndingDateTime")

            try:
                geom = _parse_umm_polygon(umm)
            except NoSpatialMetadataError:
                # If UMM parsing fails, fallback to the requested intersects geometry
                geom = intersects if intersects is not None else Polygon()

            # Find the best S3 or HTTPS link
            links = g.data_links(access="direct")
            if not links:
                links = g.data_links(access="external")

            if not links:
                logger.debug("no_links_found", concept_id=cid)
                continue

            href = links[0]

            # Estimate size
            size_mb = g.size()

            rows.append(
                {
                    "id": unique_id,
                    "collection": collection_name,
                    "geometry": geom,
                    "start_time": start_str,
                    "end_time": end_str,
                    "href": href,
                    "https_url": href if href.startswith("https") else None,
                    "size_mb": size_mb,
                    "granule_id": cid,
                }
            )

        if not rows:
            return self._empty_result()

        gdf = gpd.GeoDataFrame(rows, geometry="geometry")
        import pandas as pd

        gdf["start_time"] = pd.to_datetime(gdf["start_time"])
        gdf["end_time"] = pd.to_datetime(gdf["end_time"])

        return cast(GeoDataFrame, AssetSchema.validate(gdf))

    def _empty_result(self) -> GeoDataFrame[AssetSchema]:
        columns = list(AssetSchema.to_schema().columns.keys())
        if "geometry" not in columns:
            columns.append("geometry")
        gdf = gpd.GeoDataFrame(columns=columns, geometry="geometry")
        return cast(GeoDataFrame, AssetSchema.validate(gdf))
