#!/usr/bin/env python3
"""
Land Navigation Course Generator

Reads a CSV of point names + MGRS grids, builds N unique land nav courses
(each anchored on a start point, SP#), and outputs a consolidated PDF
with one page per course listing point name, grid, and a punch box.

CSV format expected (header row required):
    PointName,MGRS
    SP1,18SUJ2345067890
    P1,18SUJ2350068000
    ...

Start points must be named starting with "SP" (e.g. SP1, SP2, SP3).
All other points are treated as course points (P1, P2, ...).

Usage:
    python landnav_generator.py --csv points.csv --out courses.pdf \
        --num-courses 10 --min-points 4 --max-points 6 \
        --min-distance 100 --max-leg-distance 800 --seed 42
"""

import argparse
import csv
import math
import random
import sys
from dataclasses import dataclass

from pygeodesy.mgrs import parseMGRS
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Point:
    name: str
    mgrs: str
    lat: float
    lon: float

    @property
    def is_start(self) -> bool:
        return self.name.upper().startswith("SP")


# ---------------------------------------------------------------------------
# CSV / MGRS loading
# ---------------------------------------------------------------------------

def load_points(csv_path: str) -> list[Point]:
    """Load points from CSV and convert MGRS -> lat/lon.

    Uses pygeodesy (pure Python, no native/compiled dependency) instead of
    the 'mgrs' package, which wraps a native GeoTrans C extension that's
    fragile to bundle correctly with PyInstaller across platforms.
    """
    points = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # normalize header names (case/space insensitive)
        fieldmap = {k.strip().lower(): k for k in reader.fieldnames or []}
        name_key = fieldmap.get("pointname") or fieldmap.get("point name") or fieldmap.get("name")
        mgrs_key = fieldmap.get("mgrs") or fieldmap.get("grid") or fieldmap.get("mgrs location")
        if not name_key or not mgrs_key:
            raise ValueError(
                f"CSV must have 'PointName' and 'MGRS' columns. Found: {reader.fieldnames}"
            )
        for row in reader:
            name = row[name_key].strip()
            grid = row[mgrs_key].strip().replace(" ", "")
            if not name or not grid:
                continue
            try:
                ll = parseMGRS(grid).toLatLon()
                lat, lon = ll.lat, ll.lon
            except Exception as e:
                raise ValueError(f"Bad MGRS grid '{grid}' for point '{name}': {e}")
            points.append(Point(name=name, mgrs=grid, lat=lat, lon=lon))
    if not points:
        raise ValueError("No points loaded from CSV.")
    return points


# ---------------------------------------------------------------------------
# Distance calc (haversine, meters)
# ---------------------------------------------------------------------------

EARTH_RADIUS_M = 6371000.0


def distance_m(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Course generation
# ---------------------------------------------------------------------------

@dataclass
class Course:
    course_num: int
    start: Point
    points: list[Point]  # ordered route, not including start


def pairwise_ok(candidates: list[Point], min_distance: float, max_leg: float | None) -> bool:
    """Check min separation between every pair, and optionally max leg
    distance along the walked sequence (candidates[0] is start)."""
    n = len(candidates)
    for i in range(n):
        for j in range(i + 1, n):
            d = distance_m(candidates[i], candidates[j])
            if d < min_distance:
                return False
    if max_leg is not None:
        for i in range(n - 1):
            if distance_m(candidates[i], candidates[i + 1]) > max_leg:
                return False
    return True


def generate_courses(
    points: list[Point],
    num_courses: int,
    min_points: int,
    max_points: int,
    min_distance: float,
    max_leg_distance: float | None,
    seed: int | None,
    max_attempts_per_course: int = 2000,
) -> list[Course]:
    rng = random.Random(seed)

    start_points = [p for p in points if p.is_start]
    course_points = [p for p in points if not p.is_start]

    if not start_points:
        raise ValueError("No start points found (names must begin with 'SP').")
    if len(course_points) < min_points:
        raise ValueError(
            f"Not enough non-start points ({len(course_points)}) for min-points={min_points}."
        )

    used_point_sets: set[frozenset] = set()  # uniqueness key = frozenset of NON-start points used
    courses: list[Course] = []

    course_num = 0
    total_attempts = 0
    max_total_attempts = num_courses * max_attempts_per_course

    while len(courses) < num_courses and total_attempts < max_total_attempts:
        total_attempts += 1
        k = rng.randint(min_points, max_points)
        if k > len(course_points):
            k = len(course_points)

        sp = rng.choice(start_points)
        sample = rng.sample(course_points, k)

        key = frozenset(p.name for p in sample)
        if key in used_point_sets:
            continue

        route = [sp] + sample
        if not pairwise_ok(route, min_distance, max_leg_distance):
            continue

        # random walk order among the sampled points (start fixed first)
        walk = sample[:]
        rng.shuffle(walk)
        # re-check max-leg constraint against the shuffled order specifically
        if not pairwise_ok([sp] + walk, min_distance, max_leg_distance):
            continue

        used_point_sets.add(key)
        course_num += 1
        courses.append(Course(course_num=course_num, start=sp, points=walk))

    if len(courses) < num_courses:
        print(
            f"WARNING: only generated {len(courses)}/{num_courses} unique courses "
            f"before exhausting {total_attempts} attempts. Loosen constraints "
            f"(min-distance/min-points/max-points) or add more points.",
            file=sys.stderr,
        )

    return courses


# ---------------------------------------------------------------------------
# PDF output
# ---------------------------------------------------------------------------

def write_pdf(courses: list[Course], out_path: str, map_images: dict[int, str] | None = None) -> None:
    """map_images: optional {course_num: png_path} to insert as an extra
    full-page satellite overview right after that course's table page."""
    c = canvas.Canvas(out_path, pagesize=letter)
    page_w, page_h = letter

    left_margin = 0.6 * inch
    right_margin = page_w - 0.6 * inch
    top_margin = page_h - 0.6 * inch
    bottom_margin = 0.6 * inch

    # Spreadsheet-style column layout: POINT | GRID | NOTES | PUNCH
    col_point_w = 0.9 * inch
    col_grid_w = 2.2 * inch
    col_notes_w = 2.6 * inch
    col_punch_w = right_margin - left_margin - col_point_w - col_grid_w - col_notes_w

    x0 = left_margin
    x1 = x0 + col_point_w
    x2 = x1 + col_grid_w
    x3 = x2 + col_notes_w
    x4 = right_margin  # == x3 + col_punch_w

    header_row_h = 0.45 * inch
    row_h = 1.05 * inch          # spread points out
    punch_box_size = 0.85 * inch  # much larger punch box

    def draw_course_title(course):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(left_margin, top_margin, f"Course {course.course_num}")
        c.setFont("Helvetica", 12)
        c.drawString(left_margin, top_margin - 0.3 * inch, f"Start Point: {course.start.name}")

    def draw_table_header(y):
        header_bottom = y - header_row_h
        c.setLineWidth(1.2)
        c.rect(x0, header_bottom, x4 - x0, header_row_h, stroke=1, fill=0)
        for x in (x1, x2, x3):
            c.line(x, header_bottom, x, y)
        c.setFont("Helvetica-Bold", 11)
        text_y = header_bottom + header_row_h / 2 - 4
        c.drawCentredString((x0 + x1) / 2, text_y, "POINT")
        c.drawCentredString((x1 + x2) / 2, text_y, "GRID COORDINATE (MGRS)")
        c.drawCentredString((x2 + x3) / 2, text_y, "NOTES")
        c.drawCentredString((x3 + x4) / 2, text_y, "PUNCH")
        return header_bottom

    def new_page(course, redraw_title=True):
        c.showPage()
        y = top_margin
        if redraw_title:
            draw_course_title(course)
            y = top_margin - 0.55 * inch
        return draw_table_header(y)

    for course in courses:
        draw_course_title(course)
        y = draw_table_header(top_margin - 0.55 * inch)

        c.setLineWidth(0.75)
        c.setFont("Helvetica", 12)

        all_points = [course.start] + course.points
        for pt in all_points:
            if y - row_h < bottom_margin:
                y = new_page(course, redraw_title=False)

            row_bottom = y - row_h
            # row outer + column dividers
            c.rect(x0, row_bottom, x4 - x0, row_h, stroke=1, fill=0)
            for x in (x1, x2, x3):
                c.line(x, row_bottom, x, y)

            text_y = row_bottom + row_h / 2 - 4
            c.drawCentredString((x0 + x1) / 2, text_y, pt.name)
            c.drawCentredString((x1 + x2) / 2, text_y, pt.mgrs)
            # NOTES cell intentionally left blank for hand-written notes

            # large punch box, centered in the punch column
            box_x = (x3 + x4) / 2 - punch_box_size / 2
            box_y = row_bottom + row_h / 2 - punch_box_size / 2
            c.setLineWidth(1.3)
            c.rect(box_x, box_y, punch_box_size, punch_box_size)
            c.setLineWidth(0.75)

            y = row_bottom

        c.showPage()

    # All course maps go at the end of the document, in the same course order.
    if map_images:
        for course in courses:
            map_path = map_images.get(course.course_num)
            if not map_path:
                continue
            img_margin = 0.5 * inch
            avail_w = page_w - 2 * img_margin
            avail_h = page_h - 2 * img_margin
            c.drawImage(
                map_path, img_margin, img_margin, width=avail_w, height=avail_h,
                preserveAspectRatio=True, anchor="c",
            )
            c.showPage()

    c.save()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate unique land navigation courses from a CSV of MGRS points.")
    ap.add_argument("--csv", required=True, help="Input CSV with PointName,MGRS columns")
    ap.add_argument("--out", default="courses.pdf", help="Output PDF path")
    ap.add_argument("--num-courses", type=int, default=10, help="Number of unique courses to generate")
    ap.add_argument("--min-points", type=int, default=4, help="Min non-start points per course")
    ap.add_argument("--max-points", type=int, default=6, help="Max non-start points per course")
    ap.add_argument("--min-distance", type=float, default=100.0, help="Min distance (m) between any two points in a course")
    ap.add_argument("--max-leg-distance", type=float, default=None, help="Optional max distance (m) between consecutive points in the route")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    ap.add_argument("--static-maps-dir", default=None,
                     help="If set, generate a satellite map PNG per course in this folder "
                          "and embed each as an extra page in the PDF (needs internet)")
    ap.add_argument("--interactive-map", default=None,
                     help="If set, also write a single interactive HTML map (all courses, "
                          "toggleable layers) to this path (tiles load in-browser, needs internet)")
    args = ap.parse_args()

    if args.min_points > args.max_points:
        ap.error("--min-points cannot exceed --max-points")

    points = load_points(args.csv)
    courses = generate_courses(
        points=points,
        num_courses=args.num_courses,
        min_points=args.min_points,
        max_points=args.max_points,
        min_distance=args.min_distance,
        max_leg_distance=args.max_leg_distance,
        seed=args.seed,
    )

    map_images = None
    if args.static_maps_dir:
        import os
        from map_generator import draw_static_course_map
        os.makedirs(args.static_maps_dir, exist_ok=True)
        map_images = {}
        for course in courses:
            png_path = os.path.join(args.static_maps_dir, f"course_{course.course_num}.png")
            draw_static_course_map(course, png_path)
            map_images[course.course_num] = png_path
            print(f"  map: course {course.course_num} -> {png_path}")

    if args.interactive_map:
        from map_generator import draw_interactive_map
        draw_interactive_map(courses, args.interactive_map)
        print(f"Interactive map -> {args.interactive_map}")

    write_pdf(courses, args.out, map_images=map_images)
    print(f"Generated {len(courses)} course(s) -> {args.out}")


if __name__ == "__main__":
    main()