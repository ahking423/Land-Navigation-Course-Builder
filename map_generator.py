#!/usr/bin/env python3
"""
map_generator.py

Satellite-imagery overlays for land nav courses.

- draw_static_course_map(): one PNG per course, Esri World Imagery basemap,
  route + points, MGRS grid lines, scale bar, north arrow. Meant to be
  embedded as an extra PDF page per course.
- draw_interactive_map(): single HTML file (Leaflet via folium), Esri
  World Imagery basemap, one toggleable layer per course, a toggleable
  MGRS grid layer, scale control, north arrow.

Both need internet access to Esri's tile servers at *view/render* time.
The interactive HTML only needs internet when it's opened in a browser
(tiles are not baked in); the static PNGs need internet at *generation*
time, since the imagery has to be fetched and baked into the image.

Tile fetching for the static maps is hand-rolled (urllib + Pillow) rather
than using contextily/rasterio — see the comment above fetch_basemap()
for why.
"""

import io
import math
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import folium
from PIL import Image
from matplotlib_scalebar.scalebar import ScaleBar
from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)
WEBMERC = CRS.from_epsg(3857)

_to_3857 = Transformer.from_crs(WGS84, WEBMERC, always_xy=True)

# Esri's ArcGIS REST tile scheme orders path segments {z}/{y}/{x} (row
# before column) — different from the more common OSM-style {z}/{x}/{y}.
# Using named placeholders below means this is handled correctly either way.
ESRI_WORLD_IMAGERY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

TILE_SIZE = 256
_TILE_USER_AGENT = "LandNavCourseGenerator/1.0"


# ---------------------------------------------------------------------------
# Standalone XYZ tile fetching (replaces contextily/rasterio).
#
# contextily pulls in rasterio, which wraps GDAL as a compiled native
# extension. PyInstaller can't reliably freeze it — some of its internal
# imports aren't visible to static analysis even with --collect-all, and
# the exact failure mode varies by machine (a dev box with GDAL/conda/QGIS
# already installed can mask the gap; a clean machine can't). This module
# fetches and stitches the same Esri imagery tiles itself using only the
# standard library (urllib) and Pillow (already a matplotlib dependency),
# neither of which has this problem.
# ---------------------------------------------------------------------------

def _deg2num(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Lat/lon -> XYZ tile indices at a given zoom (standard slippy-map math)."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    xtile = max(0, min(int(n) - 1, xtile))
    ytile = max(0, min(int(n) - 1, ytile))
    return xtile, ytile


def _num2deg(xtile: float, ytile: float, zoom: int) -> tuple[float, float]:
    """XYZ tile indices (possibly fractional, for tile edges) -> lat/lon."""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


def _pick_zoom(min_lat, min_lon, max_lat, max_lon, max_tiles_per_side=6, max_zoom=18):
    """Pick the highest zoom whose tile mosaic still fits within
    max_tiles_per_side x max_tiles_per_side, to bound download size."""
    for zoom in range(max_zoom, 0, -1):
        x0, y0 = _deg2num(max_lat, min_lon, zoom)
        x1, y1 = _deg2num(min_lat, max_lon, zoom)
        nx = abs(x1 - x0) + 1
        ny = abs(y1 - y0) + 1
        if nx <= max_tiles_per_side and ny <= max_tiles_per_side:
            return zoom
    return 1


def _fetch_tile(z: int, x: int, y: int, url_template: str) -> Image.Image:
    url = url_template.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": _TILE_USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def fetch_basemap(min_lat, min_lon, max_lat, max_lon,
                   url_template=ESRI_WORLD_IMAGERY_URL, max_tiles_per_side=6,
                   tile_cache=None, max_workers=8):
    """Fetch and stitch XYZ tiles covering the given lat/lon box.

    Returns (mosaic: PIL.Image, extent: (x_min, x_max, y_min, y_max) in
    EPSG:3857 meters), ready to hand straight to matplotlib's ax.imshow().
    Any individual tile that fails to download (network hiccup, etc.) is
    replaced with a plain gray placeholder rather than failing the whole map.

    Tiles are downloaded concurrently (network I/O releases the GIL, so
    threading gives a near-linear speedup here), and `tile_cache` — a plain
    dict the caller can create once and pass into every call — lets tiles
    shared between overlapping courses get fetched only once instead of
    once per course. Both matter a lot in practice: a handful of courses
    drawn from the same local point pool overlap heavily in tile coverage.
    """
    cache = {} if tile_cache is None else tile_cache

    zoom = _pick_zoom(min_lat, min_lon, max_lat, max_lon, max_tiles_per_side)
    x0, y0 = _deg2num(max_lat, min_lon, zoom)  # top-left tile
    x1, y1 = _deg2num(min_lat, max_lon, zoom)  # bottom-right tile
    x_start, x_end = min(x0, x1), max(x0, x1)
    y_start, y_end = min(y0, y1), max(y0, y1)

    n_cols = x_end - x_start + 1
    n_rows = y_end - y_start + 1
    mosaic = Image.new("RGB", (n_cols * TILE_SIZE, n_rows * TILE_SIZE), (60, 60, 60))

    needed = [(tx, ty) for tx in range(x_start, x_end + 1) for ty in range(y_start, y_end + 1)]
    to_fetch = [(tx, ty) for tx, ty in needed if (zoom, tx, ty, url_template) not in cache]

    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(to_fetch))) as ex:
            future_to_tile = {
                ex.submit(_fetch_tile, zoom, tx, ty, url_template): (tx, ty)
                for tx, ty in to_fetch
            }
            for future in as_completed(future_to_tile):
                tx, ty = future_to_tile[future]
                try:
                    cache[(zoom, tx, ty, url_template)] = future.result()
                except (urllib.error.URLError, TimeoutError, OSError):
                    cache[(zoom, tx, ty, url_template)] = None  # cache the miss too

    for tx, ty in needed:
        tile = cache.get((zoom, tx, ty, url_template))
        if tile is not None:
            i, j = tx - x_start, ty - y_start
            mosaic.paste(tile, (i * TILE_SIZE, j * TILE_SIZE))

    lat_tl, lon_tl = _num2deg(x_start, y_start, zoom)
    lat_br, lon_br = _num2deg(x_end + 1, y_end + 1, zoom)
    x_min, y_max = _to_3857.transform(lon_tl, lat_tl)
    x_max, y_min = _to_3857.transform(lon_br, lat_br)
    return mosaic, (x_min, x_max, y_min, y_max)


# ---------------------------------------------------------------------------
# MGRS grid line computation (shared by both map types)
# ---------------------------------------------------------------------------

def utm_epsg(lat: float, lon: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return (32600 + zone) if lat >= 0 else (32700 + zone)


def _pick_grid_spacing(extent_m: float) -> int:
    if extent_m <= 1500:
        return 100
    if extent_m <= 6000:
        return 500
    if extent_m <= 20000:
        return 1000
    return 5000


def mgrs_gridlines(min_lat, min_lon, max_lat, max_lon, pad_frac=0.15):
    """Compute MGRS-style grid lines (constant Easting/Northing in the
    local UTM zone) covering the given lat/lon box, with some padding.

    Returns (lines, spacing_m) where each line is:
        {"axis": "x"|"y", "value": utm_coord,
         "points_ll": [(lat1, lon1), (lat2, lon2)], "label": str}
    """
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    epsg = utm_epsg(center_lat, center_lon)
    utm = CRS.from_epsg(epsg)
    to_utm = Transformer.from_crs(WGS84, utm, always_xy=True)
    to_ll = Transformer.from_crs(utm, WGS84, always_xy=True)

    lat_pad = (max_lat - min_lat) * pad_frac or 0.002
    lon_pad = (max_lon - min_lon) * pad_frac or 0.002
    min_lat, max_lat = min_lat - lat_pad, max_lat + lat_pad
    min_lon, max_lon = min_lon - lon_pad, max_lon + lon_pad

    xs, ys = [], []
    for lat in (min_lat, max_lat):
        for lon in (min_lon, max_lon):
            x, y = to_utm.transform(lon, lat)
            xs.append(x)
            ys.append(y)
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    spacing = _pick_grid_spacing(max(x1 - x0, y1 - y0))

    lines = []
    x = math.floor(x0 / spacing) * spacing
    while x <= x1:
        lon1, lat1 = to_ll.transform(x, y0)
        lon2, lat2 = to_ll.transform(x, y1)
        lines.append({
            "axis": "x", "value": x,
            "points_ll": [(lat1, lon1), (lat2, lon2)],
            "label": f"{int(x) % 100000:05d}mE",
        })
        x += spacing

    y = math.floor(y0 / spacing) * spacing
    while y <= y1:
        lon1, lat1 = to_ll.transform(x0, y)
        lon2, lat2 = to_ll.transform(x1, y)
        lines.append({
            "axis": "y", "value": y,
            "points_ll": [(lat1, lon1), (lat2, lon2)],
            "label": f"{int(y) % 100000:05d}mN",
        })
        y += spacing

    return lines, spacing


# ---------------------------------------------------------------------------
# Static per-course map (PNG, for PDF embedding)
# ---------------------------------------------------------------------------

def draw_static_course_map(course, padding_frac=0.3, dpi=150, figsize=(8, 8), tile_cache=None):
    """Render one course's satellite overview map entirely in memory.

    Returns a BytesIO holding PNG bytes — nothing is written to disk here.
    Pass a shared `tile_cache` dict across multiple calls (one per course
    in a batch) so tiles common to overlapping courses are fetched once.
    """
    pts = [course.start] + course.points
    lats = [p.lat for p in pts]
    lons = [p.lon for p in pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    lat_pad = (max_lat - min_lat) * padding_frac or 0.003
    lon_pad = (max_lon - min_lon) * padding_frac or 0.003
    min_lat, max_lat = min_lat - lat_pad, max_lat + lat_pad
    min_lon, max_lon = min_lon - lon_pad, max_lon + lon_pad

    x0, y0 = _to_3857.transform(min_lon, min_lat)
    x1, y1 = _to_3857.transform(max_lon, max_lat)

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")

    mosaic, (bx0, bx1, by0, by1) = fetch_basemap(min_lat, min_lon, max_lat, max_lon, tile_cache=tile_cache)
    ax.imshow(mosaic, extent=[bx0, bx1, by0, by1], origin="upper", zorder=0)

    lines, spacing = mgrs_gridlines(min_lat, min_lon, max_lat, max_lon)
    for line in lines:
        (lat1, lon1), (lat2, lon2) = line["points_ll"]
        gx1, gy1 = _to_3857.transform(lon1, lat1)
        gx2, gy2 = _to_3857.transform(lon2, lat2)
        ax.plot([gx1, gx2], [gy1, gy2], color="yellow", linewidth=0.6, alpha=0.8, zorder=3)

    route_x, route_y = [], []
    for p in pts:
        x, y = _to_3857.transform(p.lon, p.lat)
        route_x.append(x)
        route_y.append(y)
    ax.plot(route_x, route_y, color="red", linewidth=1.8, linestyle="--", zorder=4)
    ax.scatter(route_x, route_y, color="red", edgecolor="white", s=100, zorder=5)
    for p, x, y in zip(pts, route_x, route_y):
        ax.annotate(
            p.name, (x, y), xytext=(7, 7), textcoords="offset points",
            fontsize=10, fontweight="bold", color="white", zorder=6,
        )

    ax.add_artist(ScaleBar(1, units="m", location="lower left", box_alpha=0.6, rotation="horizontal-only"))

    ax.annotate(
        "N", xy=(0.95, 0.90), xytext=(0.95, 0.76),
        xycoords="axes fraction", textcoords="axes fraction",
        ha="center", fontsize=14, fontweight="bold", color="white",
        arrowprops=dict(facecolor="white", edgecolor="white", width=3, headwidth=10),
    )

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(f"Course {course.course_num} — Start {course.start.name}  (grid {spacing}m)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Interactive all-courses map (HTML, Leaflet via folium)
# ---------------------------------------------------------------------------

_COLORS = ["red", "cyan", "lime", "orange", "magenta", "yellow", "deepskyblue", "white"]


def draw_interactive_map(courses, out_html, zoom_start=16):
    all_pts = [p for c in courses for p in ([c.start] + c.points)]
    if not all_pts:
        raise ValueError("No points to map.")
    avg_lat = sum(p.lat for p in all_pts) / len(all_pts)
    avg_lon = sum(p.lon for p in all_pts) / len(all_pts)

    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=zoom_start, tiles=None, control_scale=True)

    folium.TileLayer(
        tiles=ESRI_WORLD_IMAGERY_URL,
        attr="Esri World Imagery",
        name="Esri Satellite",
        overlay=False,
        control=False,
    ).add_to(m)

    for i, course in enumerate(courses):
        color = _COLORS[i % len(_COLORS)]
        fg = folium.FeatureGroup(
            name=f"Course {course.course_num} (Start {course.start.name})",
            show=(i == 0),
        )
        pts = [course.start] + course.points
        latlon = [(p.lat, p.lon) for p in pts]
        folium.PolyLine(latlon, color=color, weight=3, dash_array="6,6").add_to(fg)
        for p in pts:
            folium.CircleMarker(
                location=(p.lat, p.lon), radius=7, color=color, weight=2,
                fill=True, fill_color=color, fill_opacity=0.9,
                popup=f"{p.name} ({p.mgrs})",
            ).add_to(fg)
            folium.map.Marker(
                (p.lat, p.lon),
                icon=folium.DivIcon(
                    html=f'<div style="font-size:11pt;font-weight:bold;color:{color};'
                         f'text-shadow:1px 1px 2px #000;">{p.name}</div>'
                ),
            ).add_to(fg)
        fg.add_to(m)

    all_lats = [p.lat for p in all_pts]
    all_lons = [p.lon for p in all_pts]
    lines, spacing = mgrs_gridlines(min(all_lats), min(all_lons), max(all_lats), max(all_lons))
    grid_fg = folium.FeatureGroup(name=f"MGRS Grid ({spacing}m)", show=True)
    for line in lines:
        folium.PolyLine(line["points_ll"], color="yellow", weight=1, opacity=0.7).add_to(grid_fg)
    grid_fg.add_to(m)

    north_arrow_html = """
    <div style="position: fixed; top: 80px; right: 20px; z-index: 9999;
                background: rgba(0,0,0,0.55); padding: 6px 10px; border-radius: 4px;
                color: white; font-weight: bold; text-align: center; font-family: sans-serif;">
        <div style="font-size:18px; line-height:1;">&#8593;</div>
        <div style="font-size:11px;">N</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(north_arrow_html))

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(out_html)
    return out_html
