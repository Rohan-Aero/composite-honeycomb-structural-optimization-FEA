"""Import repository data into the database.

Source files are only ever read, never written. Every imported value keeps a pointer to its source file
(plus archive member and line/table locator), the unit as printed, and the value as printed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import checks, units
from .checks import Issue

ROOT = Path(__file__).resolve().parent.parent
SIM_DIR, IMG_DIR, README, REPORT_DIR = "Simulation Files (ANSYS)", "Simulation Images", "README.md", "Report"
REPORT_CSV = "data/report_values.csv"
SOURCE_ROOTS = (README, REPORT_DIR, SIM_DIR, IMG_DIR)
THICKNESS_DIR = re.compile(r"^(\d+(?:\.\d+)?)mm$")
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
OPTIONAL_METRICS = ("directional_deformation", "strain_energy", "volume")
# (archive-member suffix, role); first match wins
MEMBER_ROLES = (
    ("/MECH/ds.dat", "solver_input_deck"), ("/MECH/solve.out", "solver_log"), ("/MECH/file.mntr", "solver_monitor"),
    ("/MECH/file.rst", "solver_result_binary"), ("/MECH/MatML.xml", "material_definitions"),
    ("/global/MECH/SYS.mechdb", "mechanical_database"), ("/DM/SYS.scdocx", "geometry_cad_embedded"),
    (".wbpj", "workbench_project"),
)
_CORE_CSV_COLUMNS = ("record_type", "subject", "quantity", "printed_value", "pdf_page", "locator")


class ImportRejected(Exception):
    """Raised when a source cannot be imported faithfully. Nothing is committed."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__("; ".join(i.message for i in issues[:3]))


def _reject(code, message, fix, record=None):
    return ImportRejected([Issue(code, "error", None, record, message, fix)])


# ------------------------------------------------------------------ pure parsers (unit-tested on small fixtures)
def _grep(text, pattern, flags=0):
    """First regex match and its 1-based line number, or (None, None)."""
    m = re.search(pattern, text, flags)
    return (m, text.count("\n", 0, m.start()) + 1) if m else (None, None)


def parse_ds(text):
    """MAPDL input deck written by Workbench: materials, element-type->material map, load, fixed support, load area."""
    lines = text.splitlines()
    out = {"materials": {}, "type_material": {}, "pressure": None, "fixed_nodes": None, "area_mm2": None, "n_surface": 0}
    nodes, surf_quads, surf_type, pressures = {}, [], None, []
    for n, line in enumerate(lines, 1):
        low = line.lower()
        if m := re.match(r"MP,(DENS|EX|NUXY|UVID),(\d+),([^,\s!]+)", line):
            out["materials"].setdefault(int(m[2]), {})[m[1]] = (m[3], n)
        elif m := re.match(r"eblock,\d+,solid", low):  # first row of a solid block: mat, element type, ...
            t = lines[n + 1].split()  # lines[n] is the format line, lines[n+1] the first element
            out["type_material"][int(t[1])] = (int(t[0]), n)
        elif m := re.match(r"cmblock,_fixedsu,node,\s*(\d+)", low):
            out["fixed_nodes"] = (int(m[1]), n)
        elif m := re.match(r"sfe,all,\d+,pres,1,(\S+)", low):
            if float(m[1]) != 0.0:
                pressures.append((float(m[1]), n))
        elif m := re.match(r"et,(\d+),154", low):
            surf_type = int(m[1])
        elif low.startswith("nblock,") and not nodes:
            i = n + 1  # skip the format line
            while not lines[i].strip().startswith("-1"):
                t = lines[i].split()
                nodes[int(t[0])] = tuple(float(x) for x in t[1:4])
                i += 1
        elif surf_type is not None and low.startswith("eblock,") and "solid" not in low and not surf_quads:
            count = int(line.split(",")[4])
            for row in lines[n + 1:n + 1 + count]:
                surf_quads.append([int(x) for x in row.split()[5:9]])  # the four corner nodes of a SURF154 face
    if len(pressures) == 1:
        out["pressure"] = pressures[0]
    out["n_surface"] = len(surf_quads)
    if surf_quads and nodes:
        out["area_mm2"] = sum(_quad_area(*(nodes[i] for i in q)) for q in surf_quads)
    return out


def _quad_area(a, b, c, d):
    """Area of a quadrilateral from its diagonals (exact for planar quads with straight edges)."""
    d1 = [c[k] - a[k] for k in range(3)]
    d2 = [d[k] - b[k] for k in range(3)]
    cross = (d1[1] * d2[2] - d1[2] * d2[1], d1[2] * d2[0] - d1[0] * d2[2], d1[0] * d2[1] - d1[1] * d2[0])
    return 0.5 * sum(x * x for x in cross) ** 0.5


def parse_solve_out(text):
    """Solver log: release, run date, mesh counts, masses, message counts. Missing items are None."""
    out = {}
    m, ln = _grep(text, r"CURRENT JOBNAME=\S+\s+(\d\d:\d\d:\d\d)\s+([A-Z]{3}) (\d+), (\d{4})")
    out["run_local"] = f"{m[4]}-{MONTHS[m[2]]:02d}-{int(m[3]):02d} {m[1]}" if m else None
    out["run_line"] = ln
    m, ln = _grep(text, r"RELEASE=\s*(\S+ \S+)\s+BUILD=\s*(\S+)")
    out["release"], out["build"], out["release_line"] = (m[1], m[2], ln) if m else (None, None, None)
    for key, pat in (("nodes", r"Number of total nodes\s*=\s*(\d+)"), ("solid_elements", r"Number of solid elements\s*=\s*(\d+)"),
                     ("total_elements", r"Number of total elements\s*=\s*(\d+)"),
                     ("contact_elements", r"Number of contact elements\s*=\s*(\d+)"),
                     ("warnings", r"NUMBER OF WARNING MESSAGES ENCOUNTERED=\s*(\d+)"),
                     ("errors", r"NUMBER OF ERROR\s+MESSAGES ENCOUNTERED=\s*(\d+)"),
                     ("dmp_processes", r"(\d+) PARALLEL PROCESSES REQUESTED")):
        m, ln = _grep(text, pat)
        out[key], out[key + "_line"] = (int(m[1]), ln) if m else (None, None)
    m, ln = _grep(text, r"TOTAL MASS =\s*(\S+)")
    out["mass_tonne"], out["mass_line"] = (float(m[1]), ln) if m else (None, None)
    out["mass_by_type"] = {}
    m, ln = _grep(text, r"MASS SUMMARY BY ELEMENT TYPE \*\*\*")
    if m:
        for off, line in enumerate(text[m.end():].splitlines()[:12]):  # element 0 is the rest of the heading line
            row = re.match(r"\s*(\d+)\s+(\d\.\d+E[+-]\d+)\s*$", line)
            if row:
                out["mass_by_type"][int(row[1])] = (float(row[2]), ln + off)
    m, ln = _grep(text, r"ANALYSIS TYPE[ .]*([^\n]+)")
    out["analysis"], out["analysis_line"] = (m[1].strip(), ln) if m else (None, None)
    m, ln = _grep(text, r"EQUATION SOLVER OPTION[ .]*(\S+)")
    out["solver_option"], out["solver_line"] = (m[1], ln) if m else (None, None)
    m, ln = _grep(text, r"(\w+) UNITS SPECIFIED FOR INTERNAL")
    out["unit_system"], out["unit_line"] = (f"mm-tonne-s-N ({m[1]} units)", ln) if m else (None, None)
    return out


def parse_mntr(text):
    """Solution monitor: {column name: value} from the last data row, e.g. {'MxDs': -0.0068, ...}, and its line."""
    names, last = None, None
    for n, line in enumerate(text.splitlines(), 1):
        if "MxDs" in line:
            names = line.split()
        elif names and re.match(r"^\s*\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S", line):
            last = (line.split()[7:], n)
    if not (names and last):
        return {}, None
    return {k: float(v) for k, v in zip(names, last[0])}, last[1]


def parse_matml(text):
    """Workbench transfer data: {DataTransferID (MP,UVID): material name}."""
    root = ET.fromstring(text.lstrip("\ufeff"))
    return {m.findtext("DataTransferID"): m.findtext("Name")
            for m in root.findall("./ANSYSWBTransferData/Materials/Material")}


def parse_wbpj(text):
    saved = re.search(r'last-saved-utc valType="String">(\d\d)/(\d\d)/(\d{4}) ([\d:]+)<', text)
    release = re.search(r'external-version-string valType="String">([^<]*)<', text)
    return {"saved_utc": f"{saved[3]}-{saved[1]}-{saved[2]}T{saved[4]}Z" if saved else None,
            "release": release[1] if release else None}


def parse_readme(text):
    """Title, objective sentence and the 'Detailed Results' table (printed strings kept for rounding checks)."""
    lines = text.splitlines()
    out = {"title": next((l[2:].strip() for l in lines if l.startswith("# ")), None), "objective": None, "rows": []}
    for i, l in enumerate(lines):
        if l.strip() == "## Objective":
            out["objective"] = next((x.strip() for x in lines[i + 1:] if x.strip()), None)
        if l.strip() == "## Detailed Results":
            header = None
            for j in range(i + 1, len(lines)):
                row = lines[j].strip()
                if not row.startswith("|"):
                    if header:
                        break
                    continue
                cells = [c.strip() for c in row.strip("|").split("|")]
                if header is None:
                    header = cells
                elif not set(row) <= set("|-: "):
                    cols = {}
                    for name, cell in zip(header[1:], cells[1:]):
                        q = ("total_deformation" if "deformation" in name.lower() else
                             "equivalent_stress" if "stress" in name.lower() else
                             "equivalent_elastic_strain" if "strain" in name.lower() else None)
                        unit = re.search(r"\(([^)]*)\)", name)
                        if q:
                            cols[q] = (cell, unit[1] if unit else "1", name)
                    out["rows"].append({"thickness": float(re.match(r"[\d.]+", cells[0])[0]), "label": cells[0],
                                        "line": j + 1, "cols": cols})
    return out


# ------------------------------------------------------------------ file registry helpers
def _kind(rel):
    low = rel.lower()
    if rel == README:
        return "readme"
    return {".pdf": "report_pdf", ".wbpz": "ansys_archive", ".wbpj": "ansys_project", ".scdocx": "geometry",
            ".png": "image", ".csv": "curated_csv"}.get(Path(low).suffix, "file")


def _image_metric(rel):
    n = Path(rel).stem.lower()
    for key, metric in (("energy", "strain_energy"), ("stress", "equivalent_stress"), ("strain", "equivalent_elastic_strain"),
                        ("direction", "directional_deformation"), ("total", "total_deformation"), ("volume", "volume")):
        if key in n:
            return metric
    return None


def _role(rel, member):
    if member:
        return next((role for suffix, role in MEMBER_ROLES if member.endswith(suffix)), "archive_member")
    low = rel.lower()
    if "common conditions" in low:
        return "common_condition_image"
    if low.endswith(".wbpz"):
        return "workbench_archive"
    if low.endswith(".wbpj"):
        return "workbench_project_loose"
    if low.endswith(".scdocx"):
        return "geometry_cad"
    if low.endswith(".png"):
        metric = _image_metric(rel)
        return f"contour_image:{metric}" if metric else "image"
    return "file"


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return [(reader.line_num, row) for row in reader]


def _text(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


# ------------------------------------------------------------------ the import
def import_all(conn, root=ROOT):
    """Load everything in one transaction; on any problem nothing is committed."""
    root = Path(root).resolve()
    if conn.execute("SELECT 1 FROM simulation_case LIMIT 1").fetchone():
        raise _reject("IMPORT_ALREADY_DONE", "the database already contains imported data",
                      "Run `python -m plm init --force` to rebuild it from scratch.")
    readme = parse_readme(_text((root / README).read_bytes()))
    csv_rows = _read_csv(root / REPORT_CSV)
    qdef = {r["quantity"]: r for r in conn.execute("SELECT * FROM quantity_def")}
    problems = checks.check_csv_rows(
        csv_rows, REPORT_CSV, required=_CORE_CSV_COLUMNS, numeric=("value", "pdf_page"),
        enums={"record_type": {"result", "input", "material_property", "label"}},
        key=("record_type", "subject", "quantity", "component"))
    problems += [Issue("CSV_UNKNOWN_QUANTITY", "error", REPORT_CSV, f"{REPORT_CSV} line {ln}",
                       f"quantity {r['quantity']!r} is not in quantity_def or label list",
                       "Use a quantity name from quantity_def.") for ln, r in csv_rows
                 if r.get("record_type") in ("result", "input", "material_property") and r.get("quantity") not in qdef]
    folders = sorted((float(m[1]), d.name) for d in (root / SIM_DIR).iterdir()
                     if d.is_dir() and (m := THICKNESS_DIR.match(d.name)))
    bad_dirs = [d.name for d in (root / SIM_DIR).iterdir() if d.is_dir() and not THICKNESS_DIR.match(d.name)]
    problems += [Issue("CONFIG_FOLDER_NAME", "error", "configuration", d, f"folder {d!r} does not match '<thickness>mm'",
                       "Rename the folder to e.g. '1.2mm' so the face-sheet thickness can be read.") for d in bad_dirs]
    if problems:
        raise ImportRejected(problems)
    with conn:
        _load(conn, root, readme, csv_rows, qdef, folders)


def _load(conn, root, readme, csv_rows, qdef, folders):
    def ins(sql, params=()):
        return conn.execute(sql, params).lastrowid

    pid = ins("INSERT INTO project(name, description) VALUES (?, ?)", (readme["title"], readme["objective"]))
    prod = ins("INSERT INTO product(project_id, product_code, name) VALUES (?, 'HSP', ?)",
               (pid, "Sandwich honeycomb panel (PLA core, ePA-CF face sheets)"))

    # ---- 1. register every source file (and the members of every .wbpz) with its SHA-256
    sf, members = {}, {}  # (rel, member) -> id ; rel -> {role: (member, bytes)}

    def register(rel, member, data):
        sf[(rel, member)] = ins("INSERT INTO source_file(rel_path, archive_member, sha256, size_bytes, file_kind) VALUES (?,?,?,?,?)",
                                (rel, member, hashlib.sha256(data).hexdigest(), len(data), "archive_member" if member else _kind(rel)))

    paths = [p for r in SOURCE_ROOTS for p in ([root / r] if (root / r).is_file() else sorted((root / r).rglob("*"))) if p.is_file()]
    paths.append(root / REPORT_CSV)
    for p in paths:
        rel, data = p.relative_to(root).as_posix(), p.read_bytes()
        register(rel, "", data)
        if rel.endswith(".wbpz"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        blob = zf.read(info)
                        register(rel, info.filename, blob)
                        members.setdefault(rel, {})[_role(rel, info.filename)] = (info.filename, blob)
    pdfs = [k for k in sf if k[0].startswith(REPORT_DIR + "/") and k[0].endswith(".pdf")]
    if len(pdfs) != 1:
        raise _reject("REPORT_PDF", f"expected exactly one report PDF under {REPORT_DIR}/, found {len(pdfs)}",
                      "Keep a single report PDF there; its page numbers are cited by data/report_values.csv.")
    pdf_id, pdf_rel = sf[pdfs[0]], pdfs[0][0]
    material = {}

    def material_id(name):
        if name not in material:
            conn.execute("INSERT OR IGNORE INTO material(name) VALUES (?)", (name,))
            material[name] = conn.execute("SELECT material_id FROM material WHERE name = ?", (name,)).fetchone()[0]
        return material[name]

    # ---- 2. one configuration + simulation case per '<t>mm' folder
    cases = {}  # thickness -> (config_id, case_id)
    for t, dirname in folders:
        code = f"T{round(t * 100):03d}"
        archives = sorted(r for r in members if r.startswith(f"{SIM_DIR}/{dirname}/"))
        if len(archives) != 1:
            raise _reject("ARCHIVE_COUNT", f"{SIM_DIR}/{dirname}: expected exactly one .wbpz, found {len(archives)}",
                          "Keep one Workbench archive per configuration folder.", dirname)
        arch, mem = archives[0], members[archives[0]]
        need = ("solver_input_deck", "solver_log", "solver_monitor", "material_definitions")
        if any(r not in mem for r in need):
            raise _reject("ARCHIVE_MEMBERS", f"{arch} lacks {[r for r in need if r not in mem]}",
                          "Re-export the Workbench archive including the solver files.", arch)
        ds, so = parse_ds(_text(mem["solver_input_deck"][1])), parse_solve_out(_text(mem["solver_log"][1]))
        mntr, mntr_line = parse_mntr(_text(mem["solver_monitor"][1]))
        uvid = parse_matml(_text(mem["material_definitions"][1]))
        wb = parse_wbpj(_text(mem["workbench_project"][1])) if "workbench_project" in mem else {}
        ids = {r: sf[(arch, m)] for r, (m, _) in mem.items()}  # role -> source_file_id inside this archive
        deck_mat = {}  # element type -> material name
        for etype, (mid, _) in ds["type_material"].items():
            u = ds["materials"].get(mid, {}).get("UVID")
            deck_mat[etype] = uvid.get(u[0]) if u else None
        core_m = deck_mat.get(1)
        face_m = deck_mat.get(2)
        cfg = ins("INSERT INTO configuration(product_id, config_code, face_sheet_thickness_mm, core_material_id,"
                  " face_sheet_material_id, thickness_source) VALUES (?,?,?,?,?,?)",
                  (prod, code, t, material_id(core_m) if core_m else None, material_id(face_m) if face_m else None,
                   f"folder name '{dirname}'"))  # cross-checks against README, report and solver mass are in plm/checks.py
        solver = None
        if so["release"]:
            conn.execute("INSERT OR IGNORE INTO solver(name, version, build) VALUES ('ANSYS MAPDL', ?, ?)",
                         (so["release"], so["build"]))
            solver = conn.execute("SELECT solver_id FROM solver WHERE name='ANSYS MAPDL' AND version=?", (so["release"],)).fetchone()[0]
        if solver is None:
            raise _reject("SOLVER_UNKNOWN", f"{arch}: could not read the solver release from solve.out",
                          "Check that solve.out is the unmodified MAPDL log.", arch)
        case = ins("INSERT INTO simulation_case(case_code, config_id, solver_id, analysis_type, solver_run_local, project_saved_utc)"
                   " VALUES (?,?,?,?,?,?)", (f"SIM-{code}", cfg, solver, so["analysis"] or "unknown", so["run_local"], wb.get("saved_utc")))
        cases[round(t, 6)] = (cfg, case)

        def inp(cat, name, role, line, num=None, text=None, unit=None, origin="solver_file", deriv=None, src=None, loc=None):
            ins("INSERT INTO simulation_input(case_id, category, param_name, value_num, value_text, unit, origin, derivation,"
                " source_file_id, locator) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (case, cat, name, num, text, unit, origin, deriv, src or ids[role], loc or f"line {line}"))

        # analysis settings and mesh (solve.out)
        inp("analysis", "analysis_type", "solver_log", so["analysis_line"], text=so["analysis"])
        inp("analysis", "equation_solver", "solver_log", so["solver_line"], text=so["solver_option"])
        inp("analysis", "unit_system", "solver_log", so["unit_line"], text=so["unit_system"])
        if so["dmp_processes"] is not None:
            inp("analysis", "dmp_processes", "solver_log", so["dmp_processes_line"], num=so["dmp_processes"], unit="1")
        for key, name, cat in (("nodes", "node_count", "mesh"), ("solid_elements", "solid_element_count", "mesh"),
                               ("total_elements", "total_element_count", "mesh"), ("contact_elements", "contact_element_count", "mesh"),
                               ("warnings", "solver_warning_count", "analysis"), ("errors", "solver_error_count", "analysis")):
            if so[key] is not None:
                inp(cat, name, "solver_log", so[key + "_line"], num=so[key], unit="1")
        # load and boundary conditions (ds.dat)
        if ds["pressure"]:
            inp("load", "applied_pressure", "solver_input_deck", ds["pressure"][1], num=ds["pressure"][0], unit="MPa",
                loc=f"line {ds['pressure'][1]}: sfe,all,3,pres,1,{ds['pressure'][0]}")
        if ds["area_mm2"]:
            inp("load", "loaded_area", "solver_input_deck", None, num=ds["area_mm2"], unit="mm^2", origin="derived",
                deriv=f"sum of corner-node quadrilateral areas of the {ds['n_surface']} SURF154 load elements in ds.dat "
                      "(exact for planar faces with straight edges)", loc="eblock of element type with et,N,154")
            if ds["pressure"]:
                inp("load", "applied_force", "solver_input_deck", None, num=abs(ds["pressure"][0]) * ds["area_mm2"], unit="N",
                    origin="derived", deriv="|applied_pressure| x loaded_area", loc="derived from the two rows above")
        if ds["fixed_nodes"]:
            inp("boundary_condition", "fixed_support", "solver_input_deck", ds["fixed_nodes"][1], unit=None,
                text="all translational DOF constrained (d,all,all) on node component _FIXEDSU")
            inp("boundary_condition", "fixed_support_node_count", "solver_input_deck", ds["fixed_nodes"][1],
                num=ds["fixed_nodes"][0], unit="1")
        for etype, name in sorted(deck_mat.items()):
            inp("material_assignment", f"element_type_{etype}_material", "solver_input_deck", ds["type_material"][etype][1],
                text=name, loc=f"line {ds['type_material'][etype][1]}: eblock of element type {etype} (material card {ds['type_material'][etype][0]})")
        # material properties as given to the solver (units: N, mm, tonne, s)
        for mid, props in sorted(ds["materials"].items()):
            name = uvid.get(props.get("UVID", (None,))[0])
            if not name:
                continue
            for key, quantity, unit in (("EX", "youngs_modulus", "tonne s^-2 mm^-1"), ("NUXY", "poissons_ratio", "1"),
                                        ("DENS", "density", "tonne mm^-3")):
                if key in props:
                    raw, line = float(props[key][0]), props[key][1]
                    ins("INSERT INTO material_property(material_id, case_id, quantity, value, unit, original_value, original_unit,"
                        " origin, source_file_id, locator) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (material_id(name), case, quantity, units.convert(raw, unit, qdef[quantity]["canonical_unit"]),
                         qdef[quantity]["canonical_unit"], raw, unit, "solver_file", ids["solver_input_deck"],
                         f"line {line}: MP,{key},{mid}"))

        # solver-derived results
        def result(metric, comp, stat, raw, raw_unit, role, line, text=None):
            ins("INSERT INTO result_metric(case_id, metric_name, statistic, component, value, unit, original_value, original_unit,"
                " printed_text, origin, source_file_id, locator) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (case, metric, stat, comp, units.convert(raw, raw_unit, qdef[metric]["canonical_unit"]),
                 qdef[metric]["canonical_unit"], raw, raw_unit, text, "solver_file", ids[role], f"line {line}"))

        if so["mass_tonne"] is not None:
            result("total_mass", "assembly", "total", so["mass_tonne"], "tonne", "solver_log", so["mass_line"])
        for etype, (raw, line) in sorted(so["mass_by_type"].items()):
            result("element_type_mass", "core" if etype == 1 else f"face_sheet_{etype - 1}", "total", raw, "tonne", "solver_log", line)
        if "MxDs" in mntr:
            result("max_displacement_component", "assembly", "max", mntr["MxDs"], "mm", "solver_monitor", mntr_line)
        # optional metrics that exist only in binary results / screenshots -> recorded as missing, never guessed
        for metric in OPTIONAL_METRICS:
            image = next((rel for (rel, m) in sf if not m and rel.startswith(f"{IMG_DIR}/{dirname}/") and _image_metric(rel) == metric), None)
            ins("INSERT INTO result_metric(case_id, metric_name, statistic, component, value, unit, status, missing_reason,"
                " origin, source_file_id, locator) VALUES (?,?,'max','assembly',NULL,?,'missing',?,'solver_file',?,?)",
                (case, metric, qdef[metric]["canonical_unit"],
                 "no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed)"
                 + (f" and as a contour image ({image})" if image else ""),
                 ids.get("solver_result_binary", sf[(arch, "")]), "file.rst (binary, not parsed)"))

        # ---- 3. link every file that belongs to this configuration/case, with its role
        def link(rel, member, case_id=case):
            conn.execute("INSERT OR IGNORE INTO artifact_link(source_file_id, config_id, case_id, role) VALUES (?,?,?,?)",
                         (sf[(rel, member)], cfg, case_id, _role(rel, member)))

        for (rel, member) in list(sf):
            if rel.startswith(f"{SIM_DIR}/{dirname}/") or rel.startswith(f"{IMG_DIR}/{dirname}/"):
                link(rel, member)
    for (rel, member) in list(sf):  # project-wide files belong to every configuration
        if rel in (README, REPORT_CSV) or rel == pdf_rel or "Common Conditions" in rel:
            for cfg, _case in cases.values():
                conn.execute("INSERT OR IGNORE INTO artifact_link(source_file_id, config_id, case_id, role) VALUES (?,?,NULL,?)",
                             (sf[(rel, member)], cfg, "readme" if rel == README else "report_pdf" if rel == pdf_rel else
                              "transcribed_report_values" if rel == REPORT_CSV else _role(rel, member)))

    # ---- 4. documented results: README (rounded) and report Table 6 (full precision)
    readme_id = sf[(README, "")]

    def documented(case, metric, raw, raw_unit, printed, src, loc):
        unit_ok = units.dimension(raw_unit) == qdef[metric]["dimension"]
        value = units.convert(raw, raw_unit, qdef[metric]["canonical_unit"]) if unit_ok else raw  # label errors are flagged, not "fixed"
        ins("INSERT INTO result_metric(case_id, metric_name, statistic, component, value, unit, original_value, original_unit,"
            " printed_text, origin, source_file_id, locator) VALUES (?,?,'max','assembly',?,?,?,?,?,'documented',?,?)",
            (case, metric, value, qdef[metric]["canonical_unit"], raw, raw_unit, printed, src, loc))

    for row in readme["rows"]:
        if round(row["thickness"], 6) not in cases:
            raise _reject("README_ROW_WITHOUT_CONFIG", f"README results row {row['label']!r} has no matching simulation folder",
                          "Add the simulation files for this thickness or correct the README table.", row["label"])
        for metric, (cell, unit, header) in row["cols"].items():
            documented(cases[round(row["thickness"], 6)][1], metric, float(cell), unit, cell, readme_id,
                       f'{README} line {row["line"]}: row "{row["label"]}", column "{header}" = "{cell}"')
    for ln, r in csv_rows:
        where = f'report p.{r["pdf_page"]} {r["locator"]} (transcribed in {REPORT_CSV} line {ln})'
        kind, subject = r["record_type"], r["subject"]
        if kind == "label" and subject == "ALL":
            targets = list(cases.values())
        elif kind in ("result", "input", "label"):
            try:
                targets = [cases[round(float(subject), 6)]]
            except (ValueError, KeyError):
                raise _reject("REPORT_ROW_WITHOUT_CONFIG", f"{REPORT_CSV} line {ln}: no configuration for subject {subject!r}",
                              "Use a face-sheet thickness that has a simulation folder (only 'label' rows may use ALL).",
                              f"{REPORT_CSV} line {ln}")
        else:
            targets = []
        unit = units.normalise(r["printed_unit"])
        if r["printed_unit"].strip() and units.dimension(unit) is None:
            raise _reject("CSV_UNKNOWN_UNIT", f"{REPORT_CSV} line {ln}: unknown unit {r['printed_unit']!r}",
                          "Add the unit to plm/units.py or correct the CSV.", f"{REPORT_CSV} line {ln}")
        if kind == "result":
            documented(targets[0][1], r["quantity"], float(r["value"]), unit, r["printed_value"], pdf_id, where)
        elif kind == "input":
            conn.execute("INSERT INTO simulation_input(case_id, category, param_name, value_num, unit, origin, source_file_id, locator)"
                         " VALUES (?,?,?,?,?, 'documented', ?, ?)", (targets[0][1], "load", r["quantity"], float(r["value"]), unit, pdf_id, where))
        elif kind == "label":
            for _cfg, case in targets:
                conn.execute("INSERT INTO simulation_input(case_id, category, param_name, value_text, origin, source_file_id, locator)"
                             " VALUES (?,'material_assignment',?,?, 'documented', ?, ?)", (case, r["quantity"], r["printed_value"], pdf_id, where))
        else:  # material_property (case-independent, from the report)
            q = qdef[r["quantity"]]
            unit_ok = units.dimension(unit) == q["dimension"]
            raw = float(r["value"])
            conn.execute("INSERT INTO material_property(material_id, case_id, quantity, value, unit, original_value, original_unit,"
                         " origin, source_file_id, locator) VALUES (?,NULL,?,?,?,?,?, 'documented', ?, ?)",
                         (material_id(r["subject"]), r["quantity"], units.convert(raw, unit, q["canonical_unit"]) if unit_ok else raw,
                          q["canonical_unit"], raw, unit, pdf_id, where))
