#!/usr/bin/env python3
"""
serve.py - Flask backend for the keygen web app.

Endpoints:
  GET /                                           -> serve index.html
  GET /api                                        -> JSON metadata of all key types
  GET /api?key=...&bitting=...                    -> generate and return .stl binary
  GET /api/warding_preview?key=...&warding=X      -> return SVG path data for warding preview
"""

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, request, send_file, abort, Response

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SCAD_DIR    = os.path.realpath(os.path.join(BASE_DIR, "..", "scad"))
SVG_DIR     = os.path.realpath(os.path.join(BASE_DIR, "..", "resources"))
BIN_KEYGEN  = os.path.realpath(os.path.join(BASE_DIR, "..", "bin", "keygen.py"))

app = Flask(__name__, static_folder=os.path.join(BASE_DIR), static_url_path="")

# ---------------------------------------------------------------------------
# SCAD -> SVG mapping
# Maps scad filename (no path) to svg filename in resources/
# Add new entries here when adding new key modules that have their own SVG
# ---------------------------------------------------------------------------
SCAD_TO_SVG = {
    "kwikset.scad":         "kwikset.svg",
    "schlage_classic.scad": "schlage.svg",
    "schlage_primus.scad":  "schlage.svg",
    "best.scad":            "best.svg",
    "falcon_025.scad":      "falcon.svg",
    "medeco_classic.scad":  "medeco.svg",
    "medeco_biaxial.scad":  "medeco.svg",
    "medeco_M3.scad":       "medeco.svg",
    "master.scad":          "master.svg",
    "lockwood.scad":        "lockwood.svg",
    "X103-KW12.scad":       "X103-KW12.svg",
}

# ---------------------------------------------------------------------------
# SCAD file discovery
# ---------------------------------------------------------------------------
LIBRARY_FILES = {"keygen.scad", "medeco.scad"}

def get_scad_files():
    return [
        f for f in os.listdir(SCAD_DIR)
        if f.endswith(".scad") and f not in LIBRARY_FILES
    ]

# ---------------------------------------------------------------------------
# Warding SVG lookup — scoped to a specific SVG file
# ---------------------------------------------------------------------------
def get_warding_path(svg_filename, warding_name):
    """
    Return the SVG path d= string for a given warding name within a specific SVG.
    Tries case-insensitive match and also tries prefixed ids (e.g. warding_falcon_m).
    """
    svg_path = os.path.join(SVG_DIR, svg_filename)
    if not os.path.exists(svg_path):
        return None

    try:
        tree = ET.parse(svg_path)
    except Exception:
        return None

    target = warding_name.lower()

    # Build list of candidate id suffixes to try, most specific first
    # e.g. for falcon "M": tries "warding_m", then any id containing the warding name
    candidates = [
        f"warding_{target}",
    ]

    # Also try with the svg filename stem as prefix e.g. "warding_falcon_m"
    stem = os.path.splitext(svg_filename)[0].lower()
    # strip trailing numbers/underscores to get base name e.g. "falcon_025" -> "falcon"
    stem_base = re.split(r'[_\-]', stem)[0]
    candidates.append(f"warding_{stem_base}_{target}")

    for elem in tree.getroot().iter():
        eid = elem.get("id", "").lower()
        d = elem.get("d")
        if not d:
            continue
        for candidate in candidates:
            if eid == candidate:
                return d

    return None

# ---------------------------------------------------------------------------
# Metadata parsing
# ---------------------------------------------------------------------------
STANDARD_PARAMS = {"bitting", "outline_name", "outline", "warding_name", "warding"}

def parse_scad_metadata(scad_path):
    try:
        with open(scad_path) as f:
            src = f.read()
    except FileNotFoundError:
        return None

    module_body = src[src.find("{"):] if "{" in src else src
    name_m = re.search(r"\bname\s*=\s*\"([^\"]+)\"", module_body)
    name = name_m.group(1) if name_m else os.path.basename(scad_path).replace(".scad", "")

    outlines_m = re.search(r"outlines_k\s*=\s*\[([^\]]+)\]", src)
    outlines = []
    if outlines_m:
        outlines = [s.strip().strip('"') for s in outlines_m.group(1).split(",") if s.strip()]

    wardings_m = re.search(r"wardings_k\s*=\s*\[([^\]]+)\]", src)
    wardings = []
    if wardings_m:
        wardings = [s.strip().strip('"') for s in wardings_m.group(1).split(",") if s.strip()]

    desc_m = re.search(r"/\*(.*?)\*/", src, re.DOTALL)
    description = desc_m.group(1).strip() if desc_m else ""

    extra_params = {}
    module_m = re.search(r"module\s+\w+\s*\(([^)]+)\)", src, re.DOTALL)
    if module_m:
        for param in module_m.group(1).split(","):
            param = param.strip()
            kv = re.match(r"(\w+)\s*=\s*(.+)", param)
            if kv:
                pname = kv.group(1).strip()
                pdefault = kv.group(2).strip().strip('"')
                if pname not in STANDARD_PARAMS:
                    extra_params[pname] = pdefault

    return {
        "filename": scad_path,
        "name": name,
        "outlines": outlines,
        "wardings": wardings if wardings else [""],
        "description": description,
        "extra_params": extra_params,
    }


def get_all_metadata():
    result = []
    for fname in get_scad_files():
        fpath = os.path.join(SCAD_DIR, fname)
        meta = parse_scad_metadata(fpath)
        if meta:
            result.append(meta)
    return sorted(result, key=lambda x: x["name"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/warding_preview")
def warding_preview():
    """Return a minimal self-contained SVG for the given warding name."""
    warding = request.args.get("warding", "")
    key_file = request.args.get("key", "")

    if not warding:
        abort(400, "Missing warding parameter")

    # Determine which SVG to look in based on the key file
    scad_fname = os.path.basename(key_file) if key_file else ""
    svg_fname = SCAD_TO_SVG.get(scad_fname)

    path_d = None
    if svg_fname:
        path_d = get_warding_path(svg_fname, warding)

    # Fallback: try all SVGs if no mapping or not found
    if not path_d:
        for svg_fname_try in os.listdir(SVG_DIR):
            if svg_fname_try.endswith(".svg"):
                path_d = get_warding_path(svg_fname_try, warding)
                if path_d:
                    break

    if not path_d:
        abort(404, f"No SVG found for warding: {warding}")

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" id="warding_svg_inner">'
        f'<path id="warding_path" d="{path_d}" '
        'style="fill:#e2bd00;stroke:#a07800;stroke-width:0.05;'
        'stroke-linejoin:round;stroke-linecap:round;fill-opacity:1;stroke-opacity:1"/>'
        '</svg>'
    )
    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api")
def api():
    key_file = request.args.get("key")

    if not key_file:
        resp = jsonify(get_all_metadata())
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    outline = request.args.get("outline", "")
    warding = request.args.get("warding", "")
    bitting = request.args.get("bitting", "")

    real_key = os.path.realpath(key_file)
    allowed = {os.path.realpath(os.path.join(SCAD_DIR, f)) for f in get_scad_files()}
    if real_key not in allowed:
        abort(400, "Unknown key file")

    meta = parse_scad_metadata(real_key)
    extra_openscad_args = []
    if meta and meta.get("extra_params"):
        for pname, pdefault in meta["extra_params"].items():
            val = request.args.get(pname, pdefault)
            if re.match(r"^-?[\d.]+$", str(val)):
                extra_openscad_args += ["-D", f"{pname}={val}"]

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = ["python3", BIN_KEYGEN, real_key, "-o", tmp_path]
        if bitting:
            cmd += ["-b", bitting]
        if outline:
            cmd += ["-u", outline]
        if warding:
            cmd += ["-w", warding]
        cmd += extra_openscad_args

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            app.logger.error("OpenSCAD stderr: %s", result.stderr)
            abort(500, "Key generation failed")

        resp = send_file(tmp_path, mimetype="application/sla", as_attachment=False)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    except subprocess.TimeoutExpired:
        abort(504, "OpenSCAD timed out")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
