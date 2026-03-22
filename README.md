# aer-search-earthaccess

A Polylith-based search plugin for EarthData using the [`earthaccess`](https://github.com/nsidc/earthaccess) library.

## Authentication

This plugin requires an EarthData account. You can provide credentials in one of the following ways:

### Environment Variables or `.env` file
Set the following environment variables in your system or in a `.env` file in the project root:
- `EARTHDATA_USERNAME`: Your EarthData username.
- `EARTHDATA_PASSWORD`: Your EarthData password.

### `.netrc` file
Alternatively, ensure a `~/.netrc` file exists with the following data:
```bash
machine urs.earthdata.nasa.gov login <username> password <password>
```

## Usage Example

```python
from aer.spatial import GridDefinition
from aer.plugin import plugin_registry
from aer.search import SearchQuery
from aer.temporal import TimeRange
from aer.spectral import Product
from datetime import datetime
from shapely.geometry import Polygon

# 1. Define your spatial search area (e.g., using a global grid)
grid = GridDefinition(name="global", dist=100)

# Target polygon over central Mexico to ensure valid search footprint
poly = Polygon([(-102, 18), (-98, 18), (-98, 22), (-102, 22), (-102, 18)])
spatial_extent = grid.intersecting_grid_spatial_extent(poly)

# 2. Get the product you want to search (e.g., VIIRS VNP02IMG)
VNP02IMG_EA = Product.get("VNP02IMG")

# 3. Build your SearchQuery
query = SearchQuery(
    products=[VNP02IMG_EA],
    time_range=TimeRange(
        start=datetime(2025, 6, 1, 0, 0),
        end=datetime(2025, 6, 1, 18, 0),
    ),
    satellites=VNP02IMG_EA.supported_satellites,
    spatial_extent=spatial_extent,
    channels=VNP02IMG_EA.channels[:1],
    cell_overlap_mode="intersects",  # Can be "intersects" or "contains"
    options={"count": 5},            # Additional earthaccess search parameters
)

# 4. Get the search plugin and run the query
search = plugin_registry.get("earthaccess")
gdf = search(query)

# The result is a GeoDataFrame where each row is a granule that overlaps with your spatial extent
print(gdf.head())
```

---

## Project Structure

Polylith organizes your codebase into interchangeable blocks:

* `components/` – Reusable functional blocks (the core logic).
* `bases/` – Application entry points.
* `projects/` – Deployable artifacts that compose one or more bases and components.

### Development Workflow

1. **Install dependencies:**  
   ```bash
   uv sync
   ```

2. **Run tests:**  
   ```bash
   uv run pytest
   ```

## License

MIT