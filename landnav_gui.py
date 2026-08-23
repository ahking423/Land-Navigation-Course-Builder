#!/usr/bin/env python3
"""
Land Navigation Course Generator - GUI

Desktop front-end (tkinter) for landnav_generator.py. Pick a CSV of
points, set course-generation rules, generate a consolidated PDF.

Run:
    python landnav_gui.py
"""

import os
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from landnav_generator import load_points, generate_courses, write_pdf


class LandNavApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Land Nav Course Generator")
        self.geometry("620x560")
        self.minsize(750, 800)

        self.csv_path = tk.StringVar()
        self.out_path = tk.StringVar(value=os.path.join(os.getcwd(), "courses.pdf"))
        self.num_courses = tk.StringVar(value="10")
        self.min_points = tk.StringVar(value="4")
        self.max_points = tk.StringVar(value="6")
        self.min_distance = tk.StringVar(value="100")
        self.max_leg_distance = tk.StringVar(value="")   # optional
        self.seed = tk.StringVar(value="")                # optional

        self.include_static_maps = tk.BooleanVar(value=False)
        self.include_interactive_map = tk.BooleanVar(value=False)
        self.interactive_map_path = tk.StringVar(value=os.path.join(os.getcwd(), "courses_map.html"))

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        file_frame = ttk.LabelFrame(self, text="Files")
        file_frame.pack(fill="x", **pad)

        ttk.Label(file_frame, text="Input CSV:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(file_frame, textvariable=self.csv_path, width=48).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(file_frame, text="Browse...", command=self._pick_csv).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(file_frame, text="Output PDF:").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(file_frame, textvariable=self.out_path, width=48).grid(row=1, column=1, padx=6, pady=6)
        ttk.Button(file_frame, text="Save As...", command=self._pick_output).grid(row=1, column=2, padx=6, pady=6)

        cfg_frame = ttk.LabelFrame(self, text="Course Rules")
        cfg_frame.pack(fill="x", **pad)

        def add_row(row, label, var, note=""):
            ttk.Label(cfg_frame, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=5)
            ttk.Entry(cfg_frame, textvariable=var, width=14).grid(row=row, column=1, sticky="w", padx=6, pady=5)
            if note:
                ttk.Label(cfg_frame, text=note, foreground="#666").grid(row=row, column=2, sticky="w", padx=6, pady=5)

        add_row(0, "Number of courses:", self.num_courses)
        add_row(1, "Min points per course:", self.min_points)
        add_row(2, "Max points per course:", self.max_points)
        add_row(3, "Min distance between points (m):", self.min_distance)
        add_row(4, "Max leg distance (m):", self.max_leg_distance, "optional, blank = no limit")
        add_row(5, "Random seed:", self.seed, "optional, blank = random each run")

        map_frame = ttk.LabelFrame(self, text="Satellite Maps (needs internet)")
        map_frame.pack(fill="x", **pad)

        ttk.Checkbutton(
            map_frame, text="Add satellite map page per course to the PDF",
            variable=self.include_static_maps,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Checkbutton(
            map_frame, text="Also generate an interactive HTML map (all courses, toggleable)",
            variable=self.include_interactive_map, command=self._sync_interactive_row,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        self.interactive_label = ttk.Label(map_frame, text="Interactive map file:")
        self.interactive_label.grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.interactive_entry = ttk.Entry(map_frame, textvariable=self.interactive_map_path, width=38)
        self.interactive_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        self.interactive_browse_btn = ttk.Button(map_frame, text="Save As...", command=self._pick_interactive_map)
        self.interactive_browse_btn.grid(row=2, column=2, padx=6, pady=4)
        self._sync_interactive_row()

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)
        self.generate_btn = ttk.Button(action_frame, text="Generate PDF", command=self._on_generate)
        self.generate_btn.pack(side="left")
        self.open_btn = ttk.Button(action_frame, text="Open Output Folder", command=self._open_output_folder, state="disabled")
        self.open_btn.pack(side="left", padx=10)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(0, 6))

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    # ------------------------------------------------------------------
    def _pick_csv(self):
        path = filedialog.askopenfilename(
            title="Select points CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.csv_path.set(path)

    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Save PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="courses.pdf",
        )
        if path:
            self.out_path.set(path)

    def _pick_interactive_map(self):
        path = filedialog.asksaveasfilename(
            title="Save interactive map as",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html")],
            initialfile="courses_map.html",
        )
        if path:
            self.interactive_map_path.set(path)

    def _sync_interactive_row(self):
        state = "normal" if self.include_interactive_map.get() else "disabled"
        self.interactive_label.configure(state=state)
        self.interactive_entry.configure(state=state)
        self.interactive_browse_btn.configure(state=state)

    def _open_output_folder(self):
        out = self.out_path.get()
        folder = os.path.dirname(os.path.abspath(out)) or "."
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception as e:
            self._log(f"Could not open folder: {e}")

    # ------------------------------------------------------------------
    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _validate_inputs(self):
        errors = []
        if not self.csv_path.get() or not os.path.isfile(self.csv_path.get()):
            errors.append("Select a valid input CSV file.")
        if not self.out_path.get():
            errors.append("Select an output PDF path.")

        def parse_int(var, name, min_val=1):
            try:
                v = int(var.get())
                if v < min_val:
                    errors.append(f"{name} must be >= {min_val}.")
                return v
            except ValueError:
                errors.append(f"{name} must be a whole number.")
                return None

        def parse_float_opt(var, name):
            s = var.get().strip()
            if s == "":
                return None
            try:
                return float(s)
            except ValueError:
                errors.append(f"{name} must be a number (or blank).")
                return None

        num_courses = parse_int(self.num_courses, "Number of courses")
        min_points = parse_int(self.min_points, "Min points per course")
        max_points = parse_int(self.max_points, "Max points per course")
        min_distance = parse_float_opt(self.min_distance, "Min distance")
        if min_distance is None:
            min_distance = 0.0
        max_leg = parse_float_opt(self.max_leg_distance, "Max leg distance")

        seed_str = self.seed.get().strip()
        seed = None
        if seed_str:
            try:
                seed = int(seed_str)
            except ValueError:
                errors.append("Random seed must be a whole number (or blank).")

        if min_points is not None and max_points is not None and min_points > max_points:
            errors.append("Min points per course cannot exceed max points per course.")

        if errors:
            messagebox.showerror("Fix the following", "\n".join(errors))
            return None

        return {
            "num_courses": num_courses,
            "min_points": min_points,
            "max_points": max_points,
            "min_distance": min_distance,
            "max_leg_distance": max_leg,
            "seed": seed,
        }

    # ------------------------------------------------------------------
    def _on_generate(self):
        params = self._validate_inputs()
        if params is None:
            return

        # Capture Tk-variable values on the main thread; only plain
        # Python values get handed to the worker thread from here on.
        csv_path = self.csv_path.get()
        out_path = self.out_path.get()

        # Capture Tk-variable values on the main thread; only plain
        # Python values get handed to the worker thread from here on.
        csv_path = self.csv_path.get()
        out_path = self.out_path.get()
        map_opts = {
            "static": self.include_static_maps.get(),
            "interactive": self.include_interactive_map.get(),
            "interactive_path": self.interactive_map_path.get(),
        }

        self.generate_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress.start(12)
        self._log("Starting generation...")

        thread = threading.Thread(
            target=self._run_generation, args=(csv_path, out_path, params, map_opts), daemon=True
        )
        thread.start()

    def _run_generation(self, csv_path, out_path, params, map_opts):
        try:
            points = load_points(csv_path)
            self._safe_log(f"Loaded {len(points)} points from CSV.")

            courses = generate_courses(
                points=points,
                num_courses=params["num_courses"],
                min_points=params["min_points"],
                max_points=params["max_points"],
                min_distance=params["min_distance"],
                max_leg_distance=params["max_leg_distance"],
                seed=params["seed"],
            )
            self._safe_log(f"Generated {len(courses)} unique course(s).")

            if not courses:
                raise RuntimeError("No courses could be generated with the given constraints.")

            map_images = None
            if map_opts["static"]:
                self._safe_log("Fetching satellite imagery for course maps (needs internet)...")
                from map_generator import draw_static_course_map
                tile_cache = {}  # shared across courses so overlapping tiles fetch once
                map_images = {}
                for course in courses:
                    map_images[course.course_num] = draw_static_course_map(course, tile_cache=tile_cache)
                    self._safe_log(f"  map generated for course {course.course_num}")

            if map_opts["interactive"]:
                self._safe_log("Building interactive HTML map...")
                from map_generator import draw_interactive_map
                draw_interactive_map(courses, map_opts["interactive_path"])
                self._safe_log(f"Interactive map -> {map_opts['interactive_path']}")

            write_pdf(courses, out_path, map_images=map_images)
            self._safe_log(f"PDF written to: {out_path}")
            self._safe_done(success=True, message=f"Generated {len(courses)} course(s).\nSaved to:\n{out_path}")

        except Exception as e:
            self._safe_log("ERROR: " + str(e))
            self._safe_log(traceback.format_exc())
            self._safe_done(success=False, message=str(e))

    # ------------------------------------------------------------------
    # thread-safe UI callbacks
    def _safe_log(self, msg):
        self.after(0, self._log, msg)

    def _safe_done(self, success, message):
        def finish():
            self.progress.stop()
            self.generate_btn.configure(state="normal")
            if success:
                self.open_btn.configure(state="normal")
                messagebox.showinfo("Done", message)
            else:
                messagebox.showerror("Generation failed", message)
        self.after(0, finish)


def main():
    app = LandNavApp()
    app.mainloop()


if __name__ == "__main__":
    main()
