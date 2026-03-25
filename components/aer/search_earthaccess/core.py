from typing import Any, Optional

import earthaccess
import geopandas as gpd
from returns import result
from shapely.geometry import Polygon
from shapely.ops import unary_union
from structlog import get_logger
from datetime import datetime
from aer.plugin import plugin
from aer.search import SearchQuery, SearchResultSchema
from aer.spatial import GridSpatialExtent
from pandera.typing.geopandas import GeoDataFrame

logger = get_logger()


class NoSpatialMetadataError(Exception):
    """Raised when a granule has no usable spatial metadata in UMM."""


def _parse_umm_polygon(
    umm_data: dict[str, Any],
) -> result.Result[Polygon, NoSpatialMetadataError]:
    """Extract a Shapely Polygon representing the granule footprint from CMR UMM metadata.

    Handles multiple ``BoundingRectangles`` (e.g. descending passes split at the
    antimeridian) by unioning them into a single geometry.  Also handles
    ``GPolygons`` (the standard CMR key for granule-level polygon footprints,
    used by VIIRS, MODIS, and most polar-orbiting products) and falls back to
    the ``Polygons`` key.

    Returns:
        ``Success(polygon)`` on success, ``Failure(reason)`` when the granule
        carries no usable spatial metadata.
    """
    spatial = umm_data.get("SpatialExtent", {})
    horizontal = spatial.get("HorizontalSpatialDomain", {})
    geometry = horizontal.get("Geometry", {})

    # Try BoundingRectangles — union all of them
    bboxes = geometry.get("BoundingRectangles", [])
    if bboxes:
        polys = []
        for bbox in bboxes:
            w = bbox.get("WestBoundingCoordinate", 0)
            s = bbox.get("SouthBoundingCoordinate", 0)
            e = bbox.get("EastBoundingCoordinate", 0)
            n = bbox.get("NorthBoundingCoordinate", 0)
            polys.append(Polygon([(w, s), (e, s), (e, n), (w, n)]))
        return result.Success(unary_union(polys))

    # Try GPolygons — the standard CMR key for granule-level footprints
    gpolygons = geometry.get("GPolygons", [])
    if gpolygons:
        boundary = gpolygons[0].get("Boundary", {})
        points = boundary.get("Points", [])
        if points:
            coords = [(p.get("Longitude", 0), p.get("Latitude", 0)) for p in points]
            return result.Success(Polygon(coords))

    # Try Polygons (less common, kept as fallback)
    polygons = geometry.get("Polygons", [])
    if polygons:
        boundary = polygons[0].get("Boundary", {})
        points = boundary.get("Points", [])
        if points:
            coords = [(p.get("Longitude", 0), p.get("Latitude", 0)) for p in points]
            return result.Success(Polygon(coords))

    return result.Failure(NoSpatialMetadataError("Granule has no usable spatial metadata in UMM"))


@plugin(name="earthaccess", category="search")
def search_earthaccess(query: SearchQuery) -> GeoDataFrame["SearchResultSchema"]:
    """Search for earthaccess data given a SearchQuery."""
    if query.spatial_extent and "bounding_box" in query.options:
        raise ValueError(
            "Cannot specify both 'spatial_extent' and 'bounding_box'. "
            "The spatial_extent automatically derives the bounding box."
        )

    search_params = _prepare_search_params(query)
    results = earthaccess.search_data(**search_params)

    if not results:
        columns = list(SearchResultSchema.to_schema().columns.keys())
        gdf = gpd.GeoDataFrame(columns=columns, geometry="geometry")
        return SearchResultSchema.validate(gdf)

    product_by_name = {p.name: p for p in query.products}
    rows = []
    geometries = []

    for granule in results:
        granule_rows, granule_poly = _granule_to_rows(granule, query, product_by_name)

        # Skip granules with missing temporal metadata
        if granule_rows is None:
            continue

        # Filter: If spatial_extent is provided, skip granules that don't overlap any cell
        if query.spatial_extent and not granule_rows:
            continue

        for row_data in granule_rows:
            rows.append(row_data)
            geometries.append(granule_poly)

    if not rows:
        columns = list(SearchResultSchema.to_schema().columns.keys())
        gdf = gpd.GeoDataFrame(columns=columns, geometry="geometry")
        return SearchResultSchema.validate(gdf)

    gdf = gpd.GeoDataFrame(rows, geometry=geometries)
    return SearchResultSchema.validate(gdf)


def _prepare_search_params(query: SearchQuery) -> dict[str, Any]:
    """Prepare keyword arguments for earthaccess.search_data."""
    temporal = (
        query.time_range.start.strftime("%Y-%m-%d %H:%M:%S"),
        query.time_range.end.strftime("%Y-%m-%d %H:%M:%S"),
    )

    kwargs = dict(query.options)
    # Apply bounding box filter if spatial_extent is provided
    if query.spatial_extent and query.spatial_extent.grid_cells:
        all_bounds = unary_union([cell.bounds for cell in query.spatial_extent.grid_cells])
        minx, miny, maxx, maxy = all_bounds.bounds
        kwargs["bounding_box"] = (minx, miny, maxx, maxy)

    # Filter products by satellites support
    if query.satellites:
        logger.warning("Satellites filter not available in this plugin, ignoring satellite filter.")

    return {
        "short_name": [p.name for p in query.products],
        "temporal": temporal,
        **kwargs,
    }


def _granule_to_rows(
    granule: Any, query: SearchQuery, product_by_name: dict[str, Any]
) -> tuple[list[dict[str, Any]], Optional[Polygon]]:
    """Map a single earthaccess granule to exploded rows (one per cell/channel)."""
    meta = granule.get("meta", {})
    umm = granule.get("umm", {})

    # Data links
    direct_links = granule.data_links(access="direct")
    external_links = granule.data_links(access="external")
    s3_url = direct_links[0] if direct_links else None
    https_url = external_links[0] if external_links else None

    # Temporal extents
    temporal_ext = umm.get("TemporalExtent", {})
    range_dt = temporal_ext.get("RangeDateTime", {})
    start_time = range_dt.get("BeginningDateTime")
    end_time = range_dt.get("EndingDateTime")

    if not start_time or not end_time:
        logger.warning(
            "Skipping granule with missing temporal metadata",
            granule_id=meta.get("native-id"),
            start_time=start_time,
            end_time=end_time,
        )
        return None, None

    # Short name and channels
    coll_ref = umm.get("CollectionReference", {})
    extracted_product_name = coll_ref.get("ShortName")

    if extracted_product_name and extracted_product_name in product_by_name:
        p = product_by_name[extracted_product_name]
        if query.channels:
            row_channels = tuple(c for c in query.channels if c in p.channels)
        else:
            row_channels = p.channels
    else:
        row_channels = query.channels if query.channels is not None else ()

    # Footprint geometry
    poly_result = _parse_umm_polygon(umm)
    granule_poly = None
    match poly_result:
        case result.Success(poly):
            granule_poly = poly
        case result.Failure(e):
            logger.warning(
                "Failed to parse UMM polygon",
                error=e,
                granule_id=meta.get("native-id"),
            )

    base_row = {
        "product_id": extracted_product_name,
        "granule_id": meta.get("native-id"),
        "start_time": datetime.fromisoformat(start_time.replace("Z", "+00:00")),
        "end_time": datetime.fromisoformat(end_time.replace("Z", "+00:00")),
        "s3_url": s3_url,
        "https_url": https_url,
        "size_mb": granule.size(),
        "overlap_mode": query.cell_overlap_mode,
    }

    if not query.spatial_extent or not granule_poly:
        # If no spatial extent is provided, we return an empty list as we can't
        # create valid SearchResultSchema rows without grid information.
        return [], granule_poly

    overlapping_cells = _calculate_grid_cells(granule_poly, query.spatial_extent, query.cell_overlap_mode)
    if not overlapping_cells:
        return [], granule_poly

    rows = []
    for cell in overlapping_cells:
        for channel in row_channels:
            # unique_id as name, channel.c_id and granule_id
            cell_name = f"{cell.row}_{cell.col}"
            unique_id = f"{cell_name}_{channel.c_id}_{base_row['granule_id']}"
            
            # SearchResultSchema inherits from GridSchema, so it needs all grid fields.
            # Some are missing from from_grid_cell in aer-core, so we provide them here.
            row = SearchResultSchema.from_grid_cell(
                cell,
                channel,
                unique_id=unique_id,
                name=cell_name,
                row_idx=0,  # Dummy as it's not in GridCell but mandatory in schema
                col_idx=0,  # Dummy
                utm_zone=cell.epsg.split(":")[-1],
                geometry=granule_poly,
                **base_row,
            )
            rows.append(row)

    return rows, granule_poly


def _calculate_grid_cells(granule_poly: Optional[Polygon], spatial_extent: Any, overlap_mode: str) -> list[Any]:
    """Determine which grid cells overlap with the granule footprint."""
    if granule_poly is None:
        return []

    overlap_fn = granule_poly.contains if overlap_mode == "contains" else granule_poly.intersects
    cells = [cell for cell in spatial_extent.grid_cells if overlap_fn(cell.bounds)]
    return cells
