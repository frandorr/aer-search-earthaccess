import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

import geopandas as gpd
from shapely.geometry import Polygon

from aer.temporal import TimeRange
from aer.search_earthaccess import EarthAccessSearchPlugin
from aer.search_earthaccess.core import _parse_umm_polygon, NoSpatialMetadataError


def test_parse_umm_polygon_success():
    umm = {
        "SpatialExtent": {
            "HorizontalSpatialDomain": {
                "Geometry": {
                    "GPolygons": [
                        {
                            "Boundary": {
                                "Points": [
                                    {"Longitude": -10, "Latitude": -10},
                                    {"Longitude": 10, "Latitude": -10},
                                    {"Longitude": 10, "Latitude": 10},
                                    {"Longitude": -10, "Latitude": 10},
                                ]
                            }
                        }
                    ]
                }
            }
        }
    }
    polygon = _parse_umm_polygon(umm)
    assert isinstance(polygon, Polygon)
    # The parsing logic maps to Lon/Lat -> x/y
    assert list(polygon.exterior.coords) == [
        (-10, -10),
        (10, -10),
        (10, 10),
        (-10, 10),
        (-10, -10), # closed
    ]


def test_parse_umm_polygon_bounding_box():
    umm = {
        "SpatialExtent": {
            "HorizontalSpatialDomain": {
                "Geometry": {
                    "BoundingRectangles": [
                        {
                            "WestBoundingCoordinate": -10,
                            "EastBoundingCoordinate": 10,
                            "SouthBoundingCoordinate": -10,
                            "NorthBoundingCoordinate": 10,
                        }
                    ]
                }
            }
        }
    }
    polygon = _parse_umm_polygon(umm)
    assert isinstance(polygon, Polygon)


def test_parse_umm_polygon_failure():
    umm = {}
    with pytest.raises(NoSpatialMetadataError):
        _parse_umm_polygon(umm)


def test_search_earthaccess_empty():
    plugin = EarthAccessSearchPlugin()
    time_range = TimeRange(start=datetime(2023, 1, 1), end=datetime(2023, 1, 2))
    
    with patch("aer.search_earthaccess.core.earthaccess.search_data") as mock_search:
        mock_search.return_value = []
        gdf = plugin.search(collections=["VNP02IMG"], intersects=None, time_range=time_range)
        
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert gdf.empty
        assert "id" in gdf.columns
        assert "collection" in gdf.columns
        assert "href" in gdf.columns
        assert mock_search.call_count == 1
        kwargs = mock_search.call_args.kwargs
        assert kwargs["short_name"] == ["VNP02IMG"]


def test_search_earthaccess_results():
    plugin = EarthAccessSearchPlugin()
    time_range = TimeRange(start=datetime(2023, 1, 1), end=datetime(2023, 1, 2))
    
    mock_granule = MagicMock()
    mock_granule.meta.return_value = {"concept-id": "G1234"}
    mock_granule.umm.return_value = {
        "CollectionReference": {"ShortName": "VNP02IMG"},
        "TemporalExtent": {
            "RangeDateTime": {
                "BeginningDateTime": "2023-01-01T00:00:00Z",
                "EndingDateTime": "2023-01-01T00:06:00Z"
            }
        },
        "SpatialExtent": {
            "HorizontalSpatialDomain": {
                "Geometry": {
                    "BoundingRectangles": [{
                        "WestBoundingCoordinate": -10, "EastBoundingCoordinate": 10,
                        "SouthBoundingCoordinate": -10, "NorthBoundingCoordinate": 10
                    }]
                }
            }
        }
    }
    mock_granule.data_links.side_effect = lambda access: ["s3://bucket/test.nc"] if access == "direct" else []
    mock_granule.size.return_value = 50.0
    
    with patch("aer.search_earthaccess.core.earthaccess.search_data") as mock_search:
        mock_search.return_value = [mock_granule]
        
        gdf = plugin.search(
            collections=["VNP02IMG"], 
            intersects=Polygon([(-9, 36), (-1, 36), (-1, 40), (-9, 40)]), 
            time_range=time_range
        )
        
        assert not gdf.empty
        assert len(gdf) == 1
        row = gdf.iloc[0]
        assert row["collection"] == "VNP02IMG"
        assert row["href"] == "s3://bucket/test.nc"
        assert "id" in row
        
        kwargs = mock_search.call_args.kwargs
        # Bounding box is extracted from the Polgyon intersects
        assert "bounding_box" in kwargs
        assert kwargs["bounding_box"] == (-9.0, 36.0, -1.0, 40.0)


@pytest.mark.integration
@pytest.mark.slow
def test_search_earthaccess_real_vnp02img():
    plugin = EarthAccessSearchPlugin()
    time_range = TimeRange(start=datetime(2023, 1, 1, 12, 0), end=datetime(2023, 1, 1, 12, 10))
    intersects = Polygon([(-9, 36), (-1, 36), (-1, 40), (-9, 40)])
    
    gdf = plugin.search(
        collections=["VNP02IMG"],
        intersects=intersects,
        time_range=time_range
    )
    
    assert not gdf.empty, "Expected earthaccess to return at least one real granule"
    assert "href" in gdf.columns
    assert gdf.iloc[0]["collection"] == "VNP02IMG"
