"""Study-area geometry for TerraScope.

Boundary provenance (verified 2026-10-31, see
``docs/data-sources/terrascope-datasets.md``): the authoritative machine-readable
source for the Pallikaranai Marsh is the **Ramsar Sites Information Service**
(Ramsar site no. 2481, "Pallikaranai Marsh Reserve Forest", designated
2022-04-08, 1,247.54 ha; WFS polygon, CC BY 4.0). That polygon covers the
Ramsar-listed Reserve Forest only — the broader historical marsh ecosystem
(reported ~80 km² historical extent) is larger and remains covered by the
explicitly **approximate** bbox below.

Rules carried from the architecture doc:

* The approximate boundary is never presented as an official or legal wetland
  boundary; any claim computed with it records that limitation.
* ``boundary_status`` travels with the AOI object so every stage can record it
  in outputs and future evidence contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from shapely.geometry.base import BaseGeometry

__all__ = [
    "APPROXIMATE_PALLIKARANAI_BBOX_4326",
    "STUDY_CRS_EPSG",
    "StudyAOI",
    "approximate_pallikaranai_aoi",
    "load_boundary_geojson",
]

#: Documented approximate study bbox: 80.18–80.28 E, 12.86–12.99 N (EPSG:4326).
APPROXIMATE_PALLIKARANAI_BBOX_4326 = (80.18, 12.86, 80.28, 12.99)

#: Analysis CRS: UTM zone 44N (see configs/processing.example.yaml; verify
#: against the final boundary geometry when the Ramsar polygon lands).
STUDY_CRS_EPSG = 32644

_APPROX_STATUS = (
    "approximate (documented bbox; authoritative Ramsar RSIS polygon verified but not yet acquired)"
)
_APPROX_SOURCE = "docs/data-sources/terrascope-datasets.md (documented approximate study boundary)"


@dataclass(frozen=True)
class StudyAOI:
    """Study-area geometry in EPSG:4326 plus its provenance status."""

    name: str
    geometry_wgs84: BaseGeometry
    boundary_status: str
    source: str

    @property
    def bbox_wgs84(self) -> tuple[float, float, float, float]:
        """``(minx, miny, maxx, maxy)`` in EPSG:4326 (STAC ``bbox`` order)."""
        return tuple(self.geometry_wgs84.bounds)  # type: ignore[return-value]

    def geometry_in_crs(self, epsg: int) -> BaseGeometry:
        """Return the AOI geometry reprojected to *epsg*."""
        if epsg == 4326:
            return self.geometry_wgs84
        transformer = Transformer.from_crs(4326, epsg, always_xy=True)
        # interleaved=False matches pyproj's f(x, y) signature (shapely >= 2.2 API).
        return shapely.transform(self.geometry_wgs84, transformer.transform, interleaved=False)


def approximate_pallikaranai_aoi() -> StudyAOI:
    """The documented approximate Pallikaranai study AOI (bbox rectangle)."""
    minx, miny, maxx, maxy = APPROXIMATE_PALLIKARANAI_BBOX_4326
    return StudyAOI(
        name="Pallikaranai Marsh (approximate study boundary)",
        geometry_wgs84=Polygon(
            [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)]
        ),
        boundary_status=_APPROX_STATUS,
        source=_APPROX_SOURCE,
    )


def load_boundary_geojson(path: Path) -> StudyAOI:
    """Load a boundary GeoJSON file (e.g. the Ramsar RSIS polygon once acquired).

    Reads the first feature of *path* via GeoPandas and labels the AOI
    ``authoritative`` — the caller is responsible for only passing verified
    authoritative sources (the manifest records the provenance and checksum).
    """
    frame = gpd.read_file(path)
    if frame.empty:
        msg = f"Boundary file contains no features: {path}"
        raise ValueError(msg)
    if frame.crs is not None and frame.crs.to_epsg() != 4326:
        frame = frame.to_crs(4326)
    geometry = frame.geometry.iloc[0]
    properties = frame.drop(columns="geometry").iloc[0]
    name = str(properties.get("name") or properties.get("NAME") or path.stem)
    return StudyAOI(
        name=name,
        geometry_wgs84=geometry,
        boundary_status=f"authoritative (source file: {path.name}; provenance in data/manifests)",
        source=str(path),
    )


def aoi_to_geojson_dict(aoi: StudyAOI) -> dict:
    """Serialise an AOI to a GeoJSON Feature dict (for sidecars and evidence)."""
    return {
        "type": "Feature",
        "properties": {
            "name": aoi.name,
            "boundary_status": aoi.boundary_status,
            "source": aoi.source,
        },
        "geometry": mapping(aoi.geometry_wgs84),
    }


def _bbox_valid(bbox: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bbox
    return -180 <= minx < maxx <= 180 and -90 <= miny < maxy <= 90


def aoi_from_bbox(
    bbox: tuple[float, float, float, float], *, name: str = "custom bbox AOI"
) -> StudyAOI:
    """Build a StudyAOI from a ``(minx, miny, maxx, maxy)`` EPSG:4326 bbox."""
    if not _bbox_valid(bbox):
        msg = f"Invalid EPSG:4326 bbox {bbox!r}: expected (minx, miny, maxx, maxy)"
        raise ValueError(msg)
    minx, miny, maxx, maxy = bbox
    return StudyAOI(
        name=name,
        geometry_wgs84=Polygon(
            [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)]
        ),
        boundary_status="approximate (custom bbox)",
        source="CLI --bbox override",
    )
