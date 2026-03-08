# aer-search-earthaccess

A Polylith plugin for the `aer` ecosystem that integrates `earthaccess` to seamlessly search for NASA Earth observation data collections and granules.

## Installation

```bash
pip install aer-search-earthaccess
```

## Usage

Once installed, it will automatically register as an `aer.plugins` plugin.

```python
from aer.plugin import search

results = search("earthaccess", ...)
```

## Related Projects

- [aer](https://github.com/frandorr/aer)
- [earthaccess](https://github.com/nsidc/earthaccess)
