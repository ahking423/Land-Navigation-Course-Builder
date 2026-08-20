# Land Navigation Course Builder

Generate unique, randomized land navigation courses from a CSV of MGRS
points, and export a print-ready PDF punch card packet — plus optional
satellite-imagery overview maps for every course.

Built for military-style land nav training: give it a pool of points
(a set of start points `SP1`, `SP2`, ... and a set of course points
`P1`, `P2`, ...), tell it how many courses you want and what the rules
are, and it will generate that many courses with **no two courses
sharing the same set of course points** — even across different start
points.

---

## Features

- **CSV-driven**: input is just point names + MGRS grids, nothing fancier.
- **Guaranteed-unique courses**: uniqueness is enforced on the set of
  non-start points used, so `SP1: P1,P2,P3` and `SP2: P1,P2,P3` are
  treated as duplicates and rejected — not just exact route matches.
- **Configurable course shape**: points-per-course range, minimum
  separation between any two points in a course, and an optional max
  leg distance to keep routes realistic.
- **Print-ready PDF**: one spreadsheet-style page per course — point
  name, MGRS grid, a blank notes column, and a large punch box, all in
  aligned table rows.
- **Satellite map overlays** (optional): a per-course PNG map
  (Esri World Imagery) with the route plotted, MGRS grid lines, a
  scale bar, and a north arrow — appended to the end of the PDF as
  extra pages. Also generates a single interactive HTML map (Leaflet)
  with a toggleable layer per course plus a toggleable MGRS grid.
- **Two ways to run it**: a CLI (`landnav_generator.py`) for
  scripting/batch use, and a desktop GUI (`landnav_gui.py`) for
  point-and-click use.

---

## Repo Contents

| File                    | Purpose                                                        |
|--------------------------|-----------------------------------------------------------------|
| `landnav_generator.py`   | Core logic + CLI: CSV loading, course generation, PDF output.   |
| `landnav_gui.py`         | Tkinter desktop GUI, wraps the core logic.                      |
| `map_generator.py`       | Satellite map generation (static PNG + interactive HTML).       |
| `requirements.txt`       | Python dependencies.                                            |

---

## Installation

Requires **Python 3.10+** (uses modern type-hint syntax like `list[Point]`).

```bash
git clone <this-repo-url>
cd <repo-folder>
pip install -r requirements.txt
```

`requirements.txt`:

```
geodesy
reportlab
contextily
matplotlib
folium
pyproj
matplotlib-scalebar
```

### GUI dependency note

`landnav_gui.py` uses `tkinter`, which is part of the Python standard
library but is sometimes not bundled by default on Linux. If you get
`ModuleNotFoundError: No module named 'tkinter'`, install it via your
OS package manager (not pip):

```bash
# Debian/Ubuntu
sudo apt install python3-tk
```

macOS and Windows installs from python.org include Tkinter already.

### Satellite map dependency note

Satellite imagery comes from Esri's World Imagery tile service. Both
map features need **live internet access** to that service:

- **Static PNG maps** need internet *at generation time*, since the
  imagery has to be downloaded and baked into the image.
- **The interactive HTML map** doesn't need internet to *build* the
  file, but the browser needs internet the first time it's *opened*,
  since map tiles load on demand (not embedded in the HTML).

If you don't need maps, skip `--static-maps-dir` / `--interactive-map`
on the CLI, or leave both checkboxes unchecked in the GUI — the rest
of the tool works fully offline.

---

## CSV Input Format

A header row plus one row per point:

```csv
PointName,MGRS
SP1,16SED2993841230
SP2,16SED2884942623
SP3,16SED2920742029
P1,16SED2982742377
P2,16SED2843841135
P3,16SED2917442783
...
```

Rules:

- **Header** must include a point-name column and an MGRS column.
  Accepted header spellings (case-insensitive): `PointName` / `Point Name`
  / `Name`, and `MGRS` / `Grid` / `MGRS Location`.
- **Start points** are any point whose name starts with `SP`
  (case-insensitive) — `SP1`, `SP2`, `sp10`, etc.
- **Every other point** is treated as a regular course point.
- MGRS strings can include or omit spaces; they're stripped automatically.
- You need at least one start point, and at least as many regular
  points as your `--min-points` setting.

---

## Usage — CLI

```bash
python landnav_generator.py \
  --csv points.csv \
  --out courses.pdf \
  --num-courses 10 \
  --min-points 4 \
  --max-points 6 \
  --min-distance 100 \
  --max-leg-distance 800 \
  --seed 42
```

### CLI arguments

| Flag                  | Required | Default    | Description |
|------------------------|----------|------------|-------------|
| `--csv`                | Yes      | —          | Input CSV path (`PointName`, `MGRS` columns). |
| `--out`                | No       | `courses.pdf` | Output PDF path. |
| `--num-courses`        | No       | `10`       | Number of unique courses to generate. |
| `--min-points`         | No       | `4`        | Minimum non-start points per course. |
| `--max-points`         | No       | `6`        | Maximum non-start points per course. |
| `--min-distance`       | No       | `100.0`    | Minimum distance (meters) required between **every** pair of points in a course, including the start point. |
| `--max-leg-distance`   | No       | none       | Optional cap (meters) on the distance between *consecutive* points in the walked route. |
| `--seed`               | No       | random     | Random seed, for reproducible course sets. |
| `--static-maps-dir`    | No       | none       | If set, generate a satellite map PNG per course in this folder and append them to the end of the PDF. Needs internet. |
| `--interactive-map`    | No       | none       | If set, also write a single interactive HTML map (all courses, toggleable layers) to this path. Needs internet in-browser. |

### Example: courses + both map outputs

```bash
python landnav_generator.py \
  --csv points.csv \
  --out courses.pdf \
  --num-courses 15 \
  --min-points 5 \
  --max-points 7 \
  --min-distance 150 \
  --static-maps-dir ./course_maps \
  --interactive-map ./courses_map.html \
  --seed 7
```

---

## Usage — GUI

```bash
python landnav_gui.py
```

1. **Files**: browse to your input CSV, and choose where to save the output PDF.
2. **Course Rules**: set number of courses, min/max points per course,
   min distance between points, optional max leg distance, and an
   optional random seed.
3. **Satellite Maps** *(optional, needs internet)*:
   - Check *"Add satellite map page per course to the PDF"* to append
     a map page per course to the end of the PDF. PNGs are also saved
     to a `course_maps/` folder next to your output PDF.
   - Check *"Also generate an interactive HTML map"* and pick a save
     location to get the toggleable Leaflet map.
4. Click **Generate PDF**. Progress and any warnings appear in the log
   pane; generation runs in the background so the window stays responsive.
5. Once done, click **Open Output Folder** to jump straight to the result.

---

## Output — PDF Layout

The PDF has two sections, in this order:

1. **Course table pages** — one page per course, spreadsheet-style:

   | POINT | GRID COORDINATE (MGRS) | NOTES | PUNCH |
   |-------|--------------------------|-------|-------|
   | SP3   | 16SED2920742029           |       | ☐ (large box) |
   | P3    | 16SED2917442783           |       | ☐ |
   | ...   | ...                       |       | ☐ |

   Rows are generously spaced, bordered like a spreadsheet, with a
   blank **Notes** column for field annotations and an oversized
   **Punch** box for course-marker punches.

2. **Satellite map pages** *(only if maps were requested)* — one
   full-page map per course, in the same order as the table pages,
   appended after **all** table pages. Each map shows the route,
   labeled points, MGRS grid lines, a scale bar, and a north arrow.

---

## How Course Uniqueness Works

Each course is defined by:

- one **start point** (any `SP#`), and
- a set of **course points** (`P#`) chosen from the pool.

Two courses are considered duplicates — and one of them will be
rejected — if they use the **exact same set of course points**, even
if their start points differ or the points are visited in a different
order. This is enforced regardless of route ordering.

If the generator can't reach your requested `--num-courses` within its
internal attempt budget (given your point pool size and constraints),
it will generate as many unique courses as it can and print a warning
telling you to loosen `--min-distance`, widen the points-per-course
range, or add more points to the CSV.

---

## Course Generation Variables

These are the knobs available to vary course difficulty/realism:

- **Points per course** (`--min-points` / `--max-points`): course
  length, as a range so course size itself varies.
- **Minimum distance between points** (`--min-distance`): prevents
  points from being too close together within a course.
- **Maximum leg distance** (`--max-leg-distance`, optional): caps how
  far apart consecutive points in the walked route can be, to keep leg
  distances realistic for the terrain/time available.
- **Random seed** (`--seed`): fixes the random draw for reproducible
  course sets — useful for regenerating an identical packet later, or
  for debugging.
- **Start point pool**: any number of `SP#` points; each course draws
  one at random.

---

## Troubleshooting

**`ValueError: CSV must have 'PointName' and 'MGRS' columns...`**
Check your header row spelling against the accepted variants above.

**`ValueError: Bad MGRS grid '...' for point '...'`**
The MGRS string couldn't be parsed. Check for typos, missing zone
letters, or stray characters.

**`ValueError: No start points found (names must begin with 'SP').`**
None of your point names start with `SP`. Rename at least one point
(e.g. `SP1`).

**Generator warns it only produced fewer courses than requested**
Your constraints are too tight for the pool size — lower
`--min-distance`, narrow/lower `--min-points`/`--max-points`, or add
more points to the CSV.

**Satellite maps fail or hang**
Check internet connectivity to Esri's tile servers
(`server.arcgisonline.com`). Corporate proxies/firewalls sometimes
block tile services — the rest of the tool (CSV parsing, course
generation, table-only PDF) works fully offline if you skip the map flags.

**`ModuleNotFoundError: No module named 'tkinter'`**
Install your OS's tkinter package (see Installation section above);
this only affects `landnav_gui.py`, not the CLI.

---

## License

MIT License

## Contributing

Issues and PRs welcome. If you're adding a feature, please keep
`map_generator.py`'s heavier dependencies (`contextily`, `folium`,
`matplotlib`) optional/lazily imported so the core CLI keeps working
in offline, dependency-light environments.
