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
time since matplotlib has to bake the imagery into the image.
"""

import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import contextily as cx
import folium
from matplotlib_scalebar.scalebar import ScaleBar
from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)
WEBMERC = CRS.from_epsg(3857)

_to_3857 = Transformer.from_crs(WGS84, WEBMERC, always_xy=True)

ESRI_WORLD_IMAGERY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)


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

def draw_static_course_map(course, out_png, padding_frac=0.3, dpi=150, figsize=(8, 8)):
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

    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldImagery, attribution=False)

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
    fig.savefig(out_png, dpi=dpi)
    plt.close(fig)
    return out_png


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
