"""Data-quality checks.

Two layers:
  * check_csv_rows(): row-level checks on structured input files *before* they are loaded (the importer rejects
    a file that has errors; it never "repairs" it).
  * run_checks(): cross-table checks on the loaded database. Results are written to validation_issue.

Severity:  error   = the data is wrong or unusable as it stands
           warning = inconsistency or comparability problem a person must resolve; data stays usable
           info    = limitation or missing optional data worth knowing about
A passing check says only that the data is internally consistent, never that the FEA result is physically valid.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple, Optional

from . import units


class Issue(NamedTuple):
    check_code: str
    severity: str                  # error | warning | info
    table_name: Optional[str]
    record_id: Optional[str]       # human-readable identifier of the affected record
    message: str
    suggested_correction: str
    source_file_id: Optional[int] = None


def check_csv_rows(rows, label, required, numeric=(), enums=None, key=()):
    """rows: iterable of (line_no, dict). `enums` maps column -> allowed values. Returns a list of error Issues."""
    issues, seen = [], {}
    enums = enums or {}
    for line, row in rows:
        where = f"{label} line {line}"
        if None in row or any(v is None for v in row.values()):
            issues.append(Issue("CSV_MALFORMED_ROW", "error", label, where,
                                "row has a different number of fields than the header",
                                "Fix the delimiter/quoting on this line; the importer does not repair rows."))
            continue
        for col in required:
            if not (row.get(col) or "").strip():
                issues.append(Issue("CSV_MISSING_VALUE", "error", label, where, f"required column '{col}' is empty",
                                    f"Provide a value for '{col}' (or delete the row if it is not a real record)."))
        for col in numeric:
            text = (row.get(col) or "").strip()
            if text:
                try:
                    float(text)
                except ValueError:
                    issues.append(Issue("CSV_BAD_NUMBER", "error", label, where, f"column '{col}' is not a number: {text!r}",
                                        "Use a plain decimal number (no units or thousands separators)."))
        for col, allowed in enums.items():
            if (row.get(col) or "").strip() and row[col].strip() not in allowed:
                issues.append(Issue("CSV_BAD_VALUE", "error", label, where,
                                    f"column '{col}' has {row[col]!r}; allowed: {sorted(allowed)}",
                                    "Use one of the allowed values."))
        if key:
            k = tuple((row.get(c) or "").strip() for c in key)
            if k in seen:
                issues.append(Issue("CSV_DUPLICATE_KEY", "error", label, where,
                                    f"duplicate record {k} (first seen on line {seen[k]})",
                                    "Remove the duplicate or make the identifying columns unique."))
            else:
                seen[k] = line
    return issues


# =====================================================================================================
# Database-level checks
# =====================================================================================================
CORE_METRICS = ("total_deformation", "equivalent_stress", "equivalent_elastic_strain")
# files that must differ between configurations; identical content suggests a wrong file was copied
CONFIG_SPECIFIC_ROLES = ("solver_input_deck", "solver_log", "solver_monitor", "solver_result_binary", "mechanical_database",
                         "workbench_project", "workbench_project_loose", "geometry_cad", "geometry_cad_embedded",
                         "workbench_archive")
NUMERIC_COLUMNS = (("result_metric", "value", "result_id"), ("result_metric", "original_value", "result_id"),
                   ("material_property", "value", "property_id"), ("material_property", "original_value", "property_id"),
                   ("simulation_input", "value_num", "input_id"), ("configuration", "face_sheet_thickness_mm", "config_id"),
                   ("part", "thickness_mm", "part_id"), ("bom_line", "quantity", "bom_line_id"))
UNCHECKED_PARAMS = ("dmp_processes", "solver_warning_count", "solver_error_count")  # run environment, not model definition

CODES = {  # every code run_checks can emit -> what it verifies (used for the "checks executed" table)
    "FK_VIOLATION": "foreign keys resolve (links between configurations, cases, results, files)",
    "TYPE_MISMATCH": "numeric columns hold numbers",
    "REQUIRED_VALUE_MISSING": "required engineering values are present",
    "STATUS_INCONSISTENT": "result status agrees with the stored value",
    "DUPLICATE_PART_NUMBER": "part numbers are unique after normalising case, dashes and spaces",
    "DUPLICATE_CONFIGURATION": "no two configurations of a product share a thickness",
    "DUPLICATE_SOURCE_CONTENT": "configuration-specific files are not byte-identical across configurations",
    "UNIT_NOT_CANONICAL": "stored values use the canonical unit of their quantity",
    "UNKNOWN_UNIT": "every printed unit is in the unit dictionary",
    "UNIT_LABEL_MISMATCH": "the unit printed in the source has the dimension of the quantity",
    "INVALID_GEOMETRY": "thicknesses are positive",
    "INVALID_MATERIAL_PARAMETER": "material properties are physically admissible (E>0, density>0, -1<nu<0.5)",
    "INVALID_LOAD": "load parameters are non-zero and positive where required",
    "CASE_NO_LOAD": "every case has an applied load",
    "CASE_NO_BOUNDARY_CONDITION": "every case has a support / boundary condition",
    "INVALID_RESULT_VALUE": "stress, deformation and strain magnitudes are non-negative; strain within small-strain range",
    "CONFIG_WITHOUT_CASE": "every configuration has a simulation case",
    "CASE_WITHOUT_CORE_RESULT": "every case has deformation, stress and strain results",
    "CASE_MISSING_ARTIFACT": "every case links its input deck, solver log and contour images",
    "RESULT_OPTIONAL_MISSING": "optional metrics (directional deformation, strain energy, volume) are available",
    "NOT_COMPARABLE": "cases share solver, units, load, supports, mesh counts and material data (only thickness varies)",
    "MATERIAL_CARD_INCONSISTENT": "one material has one set of properties in every solver deck",
    "README_REPORT_ROUNDING": "README values equal the report values rounded to the README precision",
    "SOLVER_VS_DOCUMENTED_DEFORMATION": "solver monitor displacement component is consistent with the documented total deformation",
    "FACE_THICKNESS_MASS_MISMATCH": "face-sheet thickness implied by solver mass matches the configuration label",
    "CORE_MASS_CONSTANT": "core mass is identical across configurations",
    "LOAD_VS_DOCUMENTED": "load derived from the solver deck matches the load stated in the report",
    "MATERIAL_DOC_VS_DECK": "material data in the report matches the data given to the solver",
    "MATERIAL_LABEL_MISMATCH": "material names in report tables match the solver deck",
    "README_CLAIM": "quantitative README claims are supported by the derived numbers",
    "REPORT_TRANSCRIPTION": "values in data/report_values.csv appear on the cited PDF page",
    "SOURCE_FILE_CHANGED": "source files on disk still match the hashes recorded at import",
    "BOM_CYCLE": "BOM has no circular parent/child relationships",
    "BOM_THICKNESS_MISMATCH": "BOM face-sheet thickness equals the configuration thickness",
    "BOM_MATERIAL_MISMATCH": "BOM part materials are used by the configuration",
    "ECR_STATUS_HISTORY": "change-request status matches its history",
    "ECR_NO_VERIFICATION": "verified/closed change requests link verification results",
    "ECR_NO_ITEMS": "submitted change requests name affected items",
    "REVISION_CHAIN": "a revision supersedes a revision of the same product",
    "DEMONSTRATION_DATA": "demonstration data is present and labelled (information)",
    "LIMITATION": "known limits of the available data (information)",
    "CHECK_ABORTED": "a check could not run to completion on the data it was given",
}


def _q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def _label(case_code, metric=None, extra=""):
    return " ".join(x for x in (case_code, metric, extra) if x)


def check_integrity(conn, root):
    out = [Issue("FK_VIOLATION", "error", t, f"rowid {rid}", f"row points at a missing {parent} record",
                 "Insert the referenced record or delete the orphan row.") for t, rid, parent, _fk in _q(conn, "PRAGMA foreign_key_check")]
    for table, col, idcol in NUMERIC_COLUMNS:
        for r in _q(conn, f"SELECT {idcol} AS id, {col} AS v, typeof({col}) AS t FROM {table}"
                          f" WHERE typeof({col}) NOT IN ('real', 'integer', 'null')"):
            out.append(Issue("TYPE_MISMATCH", "error", table, f"{idcol}={r['id']}",
                             f"{col} holds {r['t']} {r['v']!r} instead of a number",
                             "Correct the source value or re-import; do not store text in numeric fields."))
    return out


def check_required(conn, root):
    out = []
    for r in _q(conn, "SELECT config_code, face_sheet_thickness_mm t, core_material_id c, face_sheet_material_id f FROM configuration"):
        for col, val in (("face_sheet_thickness_mm", r["t"]), ("core_material_id", r["c"]), ("face_sheet_material_id", r["f"])):
            if val is None:
                out.append(Issue("REQUIRED_VALUE_MISSING", "error", "configuration", r["config_code"], f"{col} is missing",
                                 "Provide the value from the design source or mark the configuration as incomplete."))
    for r in _q(conn, "SELECT r.result_id, r.status, r.value, c.case_code, r.metric_name FROM result_metric r JOIN simulation_case c USING(case_id)"):
        rec = f"result_metric#{r['result_id']} ({_label(r['case_code'], r['metric_name'])})"
        if r["status"] == "ok" and r["value"] is None:
            out.append(Issue("REQUIRED_VALUE_MISSING", "error", "result_metric", rec, "result is marked ok but has no value",
                             "Re-import the result or set its status to 'missing' with a reason."))
        if r["status"] == "missing" and r["value"] is not None:
            out.append(Issue("STATUS_INCONSISTENT", "error", "result_metric", rec, "result is marked missing but has a value",
                             "Set the status to 'ok' or remove the value."))
    for r in _q(conn, "SELECT p.property_id, m.name, p.quantity FROM material_property p JOIN material m USING(material_id) WHERE p.value IS NULL"):
        out.append(Issue("REQUIRED_VALUE_MISSING", "error", "material_property", f"material_property#{r['property_id']} ({r['name']} {r['quantity']})",
                         "property has no value", "Provide the property value from its source."))
    for r in _q(conn, "SELECT i.input_id, c.case_code, i.param_name FROM simulation_input i JOIN simulation_case c USING(case_id)"
                      " WHERE i.value_num IS NULL AND i.value_text IS NULL"):
        out.append(Issue("REQUIRED_VALUE_MISSING", "error", "simulation_input", f"simulation_input#{r['input_id']} ({_label(r['case_code'], r['param_name'])})",
                         "input parameter has neither a numeric nor a text value", "Provide the value from the solver input."))
    return out


def check_duplicates(conn, root):
    out, seen = [], {}
    for r in _q(conn, "SELECT part_id, part_number FROM part ORDER BY part_id"):
        key = re.sub(r"[\s\-_]", "", r["part_number"]).upper()
        if key in seen:
            out.append(Issue("DUPLICATE_PART_NUMBER", "error", "part", r["part_number"],
                             f"part number {r['part_number']!r} duplicates {seen[key]!r} after normalising case, dashes and spaces",
                             "Keep one part record per part number; merge the duplicates and re-point their BOM lines."))
        seen.setdefault(key, r["part_number"])
    for r in _q(conn, "SELECT product_id, face_sheet_thickness_mm t, GROUP_CONCAT(config_code) codes FROM configuration"
                      " WHERE t IS NOT NULL GROUP BY product_id, t HAVING COUNT(*) > 1"):
        out.append(Issue("DUPLICATE_CONFIGURATION", "error", "configuration", r["codes"],
                         f"configurations {r['codes']} have the same face-sheet thickness {r['t']} mm",
                         "Merge them or correct the thickness of one of them."))
    roles = ",".join(f"'{x}'" for x in CONFIG_SPECIFIC_ROLES)
    for r in _q(conn, f"""SELECT sf.sha256, MIN(sf.source_file_id) sfid, GROUP_CONCAT(DISTINCT c.config_code) cfgs,
                  GROUP_CONCAT(DISTINCT sf.rel_path || CASE WHEN sf.archive_member <> '' THEN ' :: ' || sf.archive_member ELSE '' END) files
           FROM artifact_link l JOIN source_file sf USING(source_file_id) JOIN configuration c USING(config_id)
           WHERE l.role IN ({roles}) OR l.role LIKE 'contour_image:%'
           GROUP BY sf.sha256 HAVING COUNT(DISTINCT l.config_id) > 1"""):
        out.append(Issue("DUPLICATE_SOURCE_CONTENT", "warning", "source_file", r["files"],
                         f"byte-identical content (sha256 {r['sha256'][:12]}...) is filed under different configurations: {r['cfgs']}",
                         "Check which configuration the file really belongs to and replace the wrong copy with the correct export.",
                         r["sfid"]))
    return out


def check_units(conn, root):
    out = []
    sql = """SELECT t.{id} id, t.unit, t.original_unit, q.canonical_unit, q.dimension, t.{qty} qty, {where} w
             FROM {table} t JOIN quantity_def q ON q.quantity = t.{qty} {join}"""
    for table, idcol, qty, where, join in (
            ("result_metric", "result_id", "metric_name", "c.case_code", "JOIN simulation_case c USING(case_id)"),
            ("material_property", "property_id", "quantity", "m.name", "JOIN material m USING(material_id)")):
        for r in _q(conn, sql.format(table=table, id=idcol, qty=qty, where=where, join=join)):
            rec = f"{table}#{r['id']} ({r['w']} {r['qty']})"
            if r["unit"] != r["canonical_unit"]:
                out.append(Issue("UNIT_NOT_CANONICAL", "error", table, rec, f"stored unit {r['unit']!r}, canonical is {r['canonical_unit']!r}",
                                 "Convert the value to the canonical unit and keep the printed value in original_value/original_unit."))
            if r["original_unit"] is not None:
                dim = units.dimension(r["original_unit"])
                if dim is None:
                    out.append(Issue("UNKNOWN_UNIT", "error", table, rec, f"printed unit {r['original_unit']!r} is not in the unit dictionary",
                                     "Add the unit to plm/units.py or correct the source label."))
                elif dim != r["dimension"]:
                    out.append(Issue("UNIT_LABEL_MISMATCH", "warning", table, rec,
                                     f"source labels this {r['dimension']} quantity with unit {r['original_unit']!r} ({dim})",
                                     "Correct the unit label in the source document; the value was stored unchanged in the canonical unit."))
    for r in _q(conn, """SELECT i.input_id, i.unit, q.canonical_unit, c.case_code, i.param_name FROM simulation_input i
                         JOIN quantity_def q ON q.quantity = i.param_name JOIN simulation_case c USING(case_id)
                         WHERE i.unit IS NOT NULL AND i.unit <> q.canonical_unit"""):
        out.append(Issue("UNIT_NOT_CANONICAL", "error", "simulation_input", f"simulation_input#{r['input_id']} ({_label(r['case_code'], r['param_name'])})",
                         f"stored unit {r['unit']!r}, canonical is {r['canonical_unit']!r}", "Convert to the canonical unit."))
    return out


def check_physical(conn, root):
    out = []
    for r in _q(conn, "SELECT config_code, face_sheet_thickness_mm t FROM configuration WHERE t IS NOT NULL AND t <= 0"):
        out.append(Issue("INVALID_GEOMETRY", "error", "configuration", r["config_code"], f"face-sheet thickness {r['t']} mm is not positive",
                         "Correct the thickness from the CAD/design source."))
    for r in _q(conn, "SELECT part_number, thickness_mm t FROM part WHERE t IS NOT NULL AND t <= 0"):
        out.append(Issue("INVALID_GEOMETRY", "error", "part", r["part_number"], f"part thickness {r['t']} mm is not positive", "Correct the thickness."))
    for r in _q(conn, """SELECT p.property_id, m.name, p.quantity, p.value v FROM material_property p JOIN material m USING(material_id)
                         WHERE p.value IS NOT NULL AND typeof(p.value) IN ('real', 'integer') AND (
                           (p.quantity IN ('youngs_modulus', 'density', 'flexural_modulus', 'tensile_strength', 'flexural_strength',
                                           'shear_modulus', 'izod_impact_strength') AND p.value <= 0)
                           OR (p.quantity = 'poissons_ratio' AND (p.value <= -1 OR p.value >= 0.5)))"""):
        out.append(Issue("INVALID_MATERIAL_PARAMETER", "error", "material_property", f"material_property#{r['property_id']} ({r['name']} {r['quantity']})",
                         f"{r['quantity']} = {r['v']} is outside the physically admissible range", "Check the units and the source value."))
    for r in _q(conn, """SELECT i.input_id, c.case_code, i.param_name, i.value_num v FROM simulation_input i JOIN simulation_case c USING(case_id)
                         WHERE typeof(i.value_num) IN ('real', 'integer') AND (
                           (i.param_name = 'applied_pressure' AND i.value_num = 0)
                           OR (i.param_name IN ('applied_force', 'loaded_area', 'node_count', 'solid_element_count') AND i.value_num <= 0))"""):
        out.append(Issue("INVALID_LOAD", "error", "simulation_input", f"simulation_input#{r['input_id']} ({_label(r['case_code'], r['param_name'])})",
                         f"{r['param_name']} = {r['v']} is not a valid value", "Correct the load/mesh parameter from the solver input."))
    for r in _q(conn, "SELECT case_id, case_code FROM simulation_case"):
        names = {x[0] for x in _q(conn, "SELECT param_name FROM simulation_input WHERE case_id = ? AND origin <> 'documented'", (r["case_id"],))}
        if not names & {"applied_pressure", "applied_force"}:
            out.append(Issue("CASE_NO_LOAD", "error", "simulation_case", r["case_code"], "no applied load recorded",
                             "Import the solver input deck or add the load definition."))
        if "fixed_support" not in names:
            out.append(Issue("CASE_NO_BOUNDARY_CONDITION", "error", "simulation_case", r["case_code"], "no support / boundary condition recorded",
                             "Import the solver input deck or add the boundary condition."))
    for r in _q(conn, """SELECT r.result_id, c.case_code, r.metric_name, r.value v FROM result_metric r JOIN simulation_case c USING(case_id)
                         WHERE r.status = 'ok' AND typeof(r.value) IN ('real', 'integer')
                           AND r.metric_name IN ('total_deformation', 'equivalent_stress', 'equivalent_elastic_strain', 'total_mass', 'element_type_mass')
                           AND r.value < 0"""):
        out.append(Issue("INVALID_RESULT_VALUE", "error", "result_metric", f"result_metric#{r['result_id']} ({_label(r['case_code'], r['metric_name'])})",
                         f"{r['metric_name']} = {r['v']} is negative but is a magnitude", "Check the source value and sign convention."))
    for r in _q(conn, """SELECT r.result_id, c.case_code, r.value v FROM result_metric r JOIN simulation_case c USING(case_id)
                         WHERE r.status = 'ok' AND r.metric_name = 'equivalent_elastic_strain' AND typeof(r.value) IN ('real', 'integer') AND r.value > 1"""):
        out.append(Issue("INVALID_RESULT_VALUE", "warning", "result_metric", f"result_metric#{r['result_id']} ({r['case_code']} equivalent_elastic_strain)",
                         f"strain {r['v']} exceeds 100 %, outside the small-strain range of a linear static analysis", "Check units (percent vs ratio)."))
    return out


def check_links(conn, root):
    out = []
    for r in _q(conn, "SELECT config_code FROM configuration WHERE config_id NOT IN (SELECT config_id FROM simulation_case)"):
        out.append(Issue("CONFIG_WITHOUT_CASE", "error", "configuration", r["config_code"], "configuration has no simulation case",
                         "Import the simulation for this configuration or remove the configuration."))
    for c in _q(conn, "SELECT case_id, case_code FROM simulation_case"):
        have = {x[0] for x in _q(conn, "SELECT metric_name FROM v_result_primary WHERE case_id = ?", (c["case_id"],))}
        for m in CORE_METRICS:
            if m not in have:
                out.append(Issue("CASE_WITHOUT_CORE_RESULT", "error", "simulation_case", _label(c["case_code"], m),
                                 f"no value for core result {m}", "Import the result from the solver output or the report."))
        roles = {x[0] for x in _q(conn, "SELECT role FROM artifact_link WHERE case_id = ?", (c["case_id"],))}
        for need in ("solver_input_deck", "solver_log") + tuple(f"contour_image:{m}" for m in CORE_METRICS):
            if need not in roles:
                out.append(Issue("CASE_MISSING_ARTIFACT", "warning", "simulation_case", _label(c["case_code"], need),
                                 f"no file with role {need!r} is linked to the case", "Add the file to the repository and re-import."))
    for r in _q(conn, """SELECT r.result_id, c.case_code, r.metric_name, r.missing_reason, r.source_file_id FROM result_metric r
                         JOIN simulation_case c USING(case_id) WHERE r.status = 'missing' ORDER BY c.case_code, r.metric_name"""):
        out.append(Issue("RESULT_OPTIONAL_MISSING", "info", "result_metric", _label(r["case_code"], r["metric_name"]), r["missing_reason"],
                         "Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository.",
                         r["source_file_id"]))
    return out


def _case_params(conn):
    """case_id -> {parameter: value} for everything that defines the model (not the run environment)."""
    params = {}
    for r in _q(conn, "SELECT c.case_id, c.case_code, s.name || ' ' || s.version || ' ' || COALESCE(s.build, '') solver, c.analysis_type FROM simulation_case c JOIN solver s USING(solver_id)"):
        params[r["case_id"]] = {"case_code": r["case_code"], "solver": r["solver"], "analysis_type": r["analysis_type"]}
    for r in _q(conn, "SELECT case_id, param_name, value_num, value_text FROM simulation_input WHERE origin <> 'documented'"):
        if r["param_name"] not in UNCHECKED_PARAMS and r["case_id"] in params:  # orphans are reported by FK_VIOLATION
            params[r["case_id"]][r["param_name"]] = r["value_num"] if r["value_num"] is not None else r["value_text"]
    for r in _q(conn, """SELECT p.case_id, m.name, p.quantity, p.value FROM material_property p JOIN material m USING(material_id)
                         WHERE p.origin = 'solver_file' AND p.case_id IN (SELECT case_id FROM simulation_case) ORDER BY p.property_id"""):
        params[r["case_id"]].setdefault(f"{r['name']} {r['quantity']}", r["value"])  # first card; others handled below
    return params


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-12)
    return a == b


def check_comparability(conn, root):
    out = []
    params = _case_params(conn)
    cases = _q(conn, """SELECT c.case_id, f.product_id, f.face_sheet_thickness_mm t FROM simulation_case c JOIN configuration f USING(config_id)
                        ORDER BY f.product_id, f.face_sheet_thickness_mm""")
    by_product = {}
    for c in cases:
        by_product.setdefault(c["product_id"], []).append(c["case_id"])
    for ids in by_product.values():
        base = params[ids[0]]  # baseline = thinnest face sheet
        for other in ids[1:]:
            p = params[other]
            for key in sorted((set(base) | set(p)) - {"case_code"}):
                if not _same(base.get(key), p.get(key)):
                    out.append(Issue("NOT_COMPARABLE", "warning", "simulation_case", f"{p['case_code']} vs {base['case_code']}",
                                     f"{key} differs: {base.get(key)!r} vs {p.get(key)!r}; the cases differ in more than the face-sheet thickness",
                                     "Re-run the cases with identical settings or state the difference when comparing results."))
    for r in _q(conn, """SELECT m.name, p.quantity, GROUP_CONCAT(DISTINCT p.value) vals, COUNT(DISTINCT p.value) n FROM material_property p
                         JOIN material m USING(material_id) WHERE p.origin = 'solver_file' GROUP BY m.name, p.quantity HAVING n > 1"""):
        out.append(Issue("MATERIAL_CARD_INCONSISTENT", "warning", "material_property", f"{r['name']} {r['quantity']}",
                         f"the same material has different {r['quantity']} values in the solver decks: {r['vals']}",
                         "Use one material definition for all cases of the study."))
    return out


def _case_table(conn):
    """case_id -> flat dict of the preferred (primary) values and load inputs, ordered by thickness."""
    rows = {}
    for r in _q(conn, "SELECT c.case_id, c.case_code, CASE WHEN typeof(f.face_sheet_thickness_mm) IN ('real', 'integer') THEN f.face_sheet_thickness_mm END t, "
                      "f.face_sheet_material_id fm FROM simulation_case c JOIN configuration f USING(config_id) ORDER BY t"):
        rows[r["case_id"]] = dict(r)
    for r in _q(conn, "SELECT case_id, metric_name, component, value FROM v_result_primary WHERE typeof(value) IN ('real', 'integer')"):
        key = r["metric_name"] if r["component"] == "assembly" else f"{r['metric_name']}:{r['component']}"
        if r["case_id"] in rows:
            rows[r["case_id"]][key] = r["value"]
    for r in _q(conn, "SELECT case_id, param_name, origin, value_num FROM simulation_input "
                      "WHERE typeof(value_num) IN ('real', 'integer') AND param_name IN ('applied_force', 'loaded_area')"):
        if r["case_id"] in rows:
            rows[r["case_id"]][f"{r['param_name']}:{r['origin']}"] = r["value_num"]
    return rows


def _norm_name(name):
    return re.sub(r"[\s\-_]", "", name or "").lower()


def _readme_claims(text, cases):
    """Compare quantitative README statements with numbers derived from the imported data."""
    out = []
    usable = [c for c in cases if c.get("t") is not None and c.get("total_deformation") and c.get("total_mass")
              and (c.get("applied_force:derived") or c.get("applied_force:documented"))]
    if len(usable) < 2:
        return out
    lo, hi = usable[0], usable[-1]
    reduction = (lo["total_deformation"] - hi["total_deformation"]) / lo["total_deformation"] * 100

    def specific(c):  # stiffness proxy F/delta per unit mass, N/mm/g
        return (c.get("applied_force:derived") or c["applied_force:documented"]) / c["total_deformation"] / c["total_mass"]

    change = (specific(hi) / specific(lo) - 1) * 100
    m = re.search(r"(\d+(?:\.\d+)?)%\s+reduction in (?:total )?deformation", text)
    if m and abs(float(m[1]) - reduction) > 1.0:
        out.append(Issue("README_CLAIM", "warning", "README.md", m[0], f"README claims {m[1]} % deformation reduction; the data give "
                         f"{reduction:.1f} % between {lo['t']} and {hi['t']} mm (derived)", "Update the README figure to the value derived from the results."))
    if re.search(r"improved stiffness-to-weight", text, re.I) and change < 5.0:
        out.append(Issue("README_CLAIM", "warning", "README.md", "'Improved stiffness-to-weight ratio significantly'",
                         f"derived specific stiffness F/(deformation x mass) changes by {change:+.1f} % from {lo['t']} to {hi['t']} mm "
                         f"(mass +{(hi['total_mass'] / lo['total_mass'] - 1) * 100:.0f} %, stiffness +{(lo['total_deformation'] / hi['total_deformation'] - 1) * 100:.0f} %): "
                         "the claim is not supported by this metric (it assumes equal load and uses maximum deformation as the stiffness measure)",
                         "Define the stiffness-to-weight metric and report its values, or reword the claim (stiffness increases; stiffness per mass does not)."))
    return out


def check_cross_source(conn, root):
    out = []
    # --- README values must equal the report values rounded to the README's printed precision
    for r in _q(conn, """SELECT a.result_id, c.case_code, a.metric_name, a.value va, b.value vb, a.printed_text pa, a.original_unit ua, a.unit u, b.printed_text pb
                         FROM result_metric a JOIN source_file fa ON fa.source_file_id = a.source_file_id AND fa.file_kind = 'readme'
                         JOIN result_metric b ON b.case_id = a.case_id AND b.metric_name = a.metric_name AND b.component = a.component
                              AND b.statistic = a.statistic AND b.status = 'ok'
                         JOIN source_file fb ON fb.source_file_id = b.source_file_id AND fb.file_kind = 'report_pdf'
                         JOIN simulation_case c ON c.case_id = a.case_id WHERE a.status = 'ok'
                           AND typeof(a.value) IN ('real', 'integer') AND typeof(b.value) IN ('real', 'integer')"""):
        try:
            half = Decimal(5).scaleb(Decimal(r["pa"]).as_tuple().exponent - 1)  # half a unit of the last printed digit
            half = float(half) * units.convert(1.0, r["ua"], r["u"])
        except (ValueError, ArithmeticError, TypeError):
            continue  # unreadable printed value or unit: UNIT_* / TYPE_MISMATCH report it
        if abs(r["va"] - r["vb"]) > half * (1 + 1e-9):
            out.append(Issue("README_REPORT_ROUNDING", "error", "result_metric", f"result_metric#{r['result_id']} ({_label(r['case_code'], r['metric_name'])})",
                             f"README prints {r['pa']} but the report prints {r['pb']}; they differ by more than the README rounding",
                             "Correct whichever document is wrong after checking the ANSYS result."))
    cases = _case_table(conn)
    ordered = list(cases.values())
    core_mass = {}
    for c in ordered:
        code, defl, mx = c["case_code"], c.get("total_deformation"), c.get("max_displacement_component")
        # a displacement component cannot exceed the vector magnitude, and the largest component is at least |u|max / sqrt(3)
        if defl and mx is not None:
            ratio = abs(mx) / defl
            if not (1 / math.sqrt(3) - 1e-6 <= ratio <= 1 + 1e-6):
                out.append(Issue("SOLVER_VS_DOCUMENTED_DEFORMATION", "error", "simulation_case", code,
                                 f"solver monitor |MxDs| = {abs(mx):.6g} mm vs documented total deformation {defl:.6g} mm (ratio {ratio:.3f}); "
                                 "the ratio must lie in [0.577, 1.0] if both come from the same solution",
                                 "Check that the documented value and the archive belong to the same run/configuration."))
        # face-sheet thickness implied by mass: t = m / (rho * A), assuming a solid plate with the loaded area
        area = c.get("loaded_area:derived")
        rho = _q(conn, "SELECT value FROM material_property WHERE case_id = ? AND material_id = ? AND quantity = 'density' AND origin = 'solver_file' LIMIT 1",
                 (c["case_id"], c["fm"]))
        if area and rho and c["t"]:
            for key in sorted(k for k in c if k.startswith("element_type_mass:face_sheet")):
                implied = c[key] / rho[0][0] * 1000.0 / area
                if abs(implied - c["t"]) / c["t"] > 0.01:
                    out.append(Issue("FACE_THICKNESS_MASS_MISMATCH", "warning", "configuration", code,
                                     f"{key.split(':')[1]} mass implies a thickness of {implied:.4f} mm but the configuration says {c['t']} mm "
                                     "(assumes a solid plate with the loaded-face area)",
                                     "Confirm that this archive was solved with the thickness in its folder name."))
        if "element_type_mass:core" in c:
            core_mass[code] = c["element_type_mass:core"]
        f_der, f_doc = c.get("applied_force:derived"), c.get("applied_force:documented")
        if f_der and f_doc and abs(f_der - f_doc) / f_doc > 1e-3:
            out.append(Issue("LOAD_VS_DOCUMENTED", "warning", "simulation_case", code,
                             f"load derived from the solver deck is {f_der:.4g} N but the report states {f_doc:.4g} N",
                             "Confirm which load was actually solved and correct the report or the model."))
    if core_mass:
        ref = next(iter(core_mass.values()))
        for code, v in core_mass.items():
            if abs(v - ref) / ref > 1e-3:
                out.append(Issue("CORE_MASS_CONSTANT", "warning", "simulation_case", code,
                                 f"core mass {v:.5g} g differs from {ref:.5g} g in the baseline although only the face-sheet thickness should change",
                                 "Check that the core geometry is identical in all configurations."))
    # --- report material table vs the data given to the solver
    for r in _q(conn, """SELECT m.name, d.quantity dq, d.value dv, d.unit du, s.quantity sq, s.value sv, d.property_id
                         FROM material m JOIN material_property d ON d.material_id = m.material_id AND d.origin = 'documented'
                         JOIN material_property s ON s.material_id = m.material_id AND s.origin = 'solver_file'
                              AND ((d.quantity = 'density' AND s.quantity = 'density')
                                   OR (d.quantity = 'flexural_modulus' AND s.quantity = 'youngs_modulus'))
                         WHERE d.value IS NOT NULL AND s.value IS NOT NULL GROUP BY d.property_id"""):
        tol = 0.01 if r["dq"] == "density" else 0.05
        if abs(r["dv"] - r["sv"]) / r["sv"] > tol:
            note = "" if r["dq"] == r["sq"] else " (different quantities: flexural vs Young's modulus; confirm which one the model intends)"
            out.append(Issue("MATERIAL_DOC_VS_DECK", "warning", "material_property", f"{r['name']} {r['dq']}",
                             f"report Table 4 gives {r['dv']:g} {r['du']} but the solver deck uses {r['sv']:g} for {r['sq']}{note}",
                             "State the source of the solver material data and align the report table with it."))
    labels = {}
    for r in _q(conn, """SELECT i.param_name, i.value_text label, i.locator, a.value_text deck, c.case_code, i.source_file_id
                         FROM simulation_input i JOIN simulation_case c USING(case_id)
                         JOIN simulation_input a ON a.case_id = i.case_id AND a.origin = 'solver_file'
                              AND a.param_name = CASE i.param_name WHEN 'core_material_label' THEN 'element_type_1_material'
                                                 ELSE 'element_type_2_material' END
                         WHERE i.origin = 'documented' AND i.param_name IN ('core_material_label', 'face_sheet_material_label')"""):
        if _norm_name(r["label"]) != _norm_name(r["deck"]):
            labels.setdefault((r["param_name"], r["label"], r["deck"], r["source_file_id"], r["locator"]), []).append(r["case_code"])
    for (name, label, deck, sfid, locator), codes in labels.items():
        out.append(Issue("MATERIAL_LABEL_MISMATCH", "warning", "simulation_input", f"{name} ({', '.join(codes)})",
                         f"report labels the {name.split('_label')[0].replace('_', ' ')} {label!r} but the solver deck assigns {deck!r} ({locator})",
                         "Correct the table in the report (or the model if the report is right).", sfid))
    if root and (Path(root) / "README.md").is_file():
        out += _readme_claims((Path(root) / "README.md").read_text(encoding="utf-8"), ordered)
    return out


def check_bom_and_workflow(conn, root):
    out = []
    for r in _q(conn, """WITH RECURSIVE walk(config_id, root, cur, depth) AS (
                           SELECT config_id, parent_part_id, child_part_id, 1 FROM bom_line
                           UNION ALL SELECT w.config_id, w.root, b.child_part_id, w.depth + 1 FROM walk w
                             JOIN bom_line b ON b.config_id = w.config_id AND b.parent_part_id = w.cur WHERE w.depth < 20)
                         SELECT DISTINCT c.config_code, p.part_number FROM walk w JOIN configuration c USING(config_id)
                         JOIN part p ON p.part_id = w.root WHERE w.cur = w.root"""):
        out.append(Issue("BOM_CYCLE", "error", "bom_line", f"{r['config_code']} {r['part_number']}",
                         "the part is (indirectly) its own child in this BOM", "Break the circular parent/child relationship."))
    for r in _q(conn, """SELECT c.config_code, p.part_number, p.thickness_mm pt, c.face_sheet_thickness_mm ct
                         FROM bom_line b JOIN part p ON p.part_id = b.child_part_id JOIN configuration c ON c.config_id = b.config_id
                         WHERE p.thickness_mm IS NOT NULL AND c.face_sheet_thickness_mm IS NOT NULL
                           AND ABS(p.thickness_mm - c.face_sheet_thickness_mm) > 1e-9"""):
        out.append(Issue("BOM_THICKNESS_MISMATCH", "error", "bom_line", f"{r['config_code']} {r['part_number']}",
                         f"BOM part is {r['pt']} mm thick but configuration {r['config_code']} is {r['ct']} mm",
                         "Use the face-sheet part number that matches the configuration thickness."))
    for r in _q(conn, """SELECT c.config_code, p.part_number, m.name FROM bom_line b JOIN part p ON p.part_id = b.child_part_id
                         JOIN configuration c ON c.config_id = b.config_id JOIN material m ON m.material_id = p.material_id
                         WHERE p.material_id NOT IN (COALESCE(c.core_material_id, -1), COALESCE(c.face_sheet_material_id, -1))"""):
        out.append(Issue("BOM_MATERIAL_MISMATCH", "warning", "bom_line", f"{r['config_code']} {r['part_number']}",
                         f"BOM part material {r['name']} is not a core or face-sheet material of the configuration",
                         "Correct the part material or the configuration."))
    for r in _q(conn, "SELECT e.ecr_id, e.ecr_code, e.status, (SELECT to_status FROM ecr_status_history h WHERE h.ecr_id = e.ecr_id ORDER BY seq DESC LIMIT 1) last FROM change_request e"):
        if r["last"] != r["status"]:
            out.append(Issue("ECR_STATUS_HISTORY", "error", "change_request", r["ecr_code"],
                             f"status is {r['status']} but the last history entry is {r['last']}", "Change status only through plm.workflow.transition()."))
        if r["status"] != "DRAFT" and not _q(conn, "SELECT 1 FROM ecr_item WHERE ecr_id = ? AND role IN ('affected', 'proposed')", (r["ecr_id"],)):
            out.append(Issue("ECR_NO_ITEMS", "warning", "change_request", r["ecr_code"], "change request names no affected or proposed item",
                             "Add the affected parts/configurations."))
        if r["status"] in ("VERIFIED", "CLOSED"):
            cases = {x[0] for x in _q(conn, "SELECT case_id FROM ecr_item WHERE ecr_id = ? AND role = 'verification' AND case_id IS NOT NULL", (r["ecr_id"],))}
            complete = [c for c in cases if len({x[0] for x in _q(conn, "SELECT metric_name FROM v_result_primary WHERE case_id = ?", (c,))} & set(CORE_METRICS)) == len(CORE_METRICS)]
            if not complete:
                out.append(Issue("ECR_NO_VERIFICATION", "error", "change_request", r["ecr_code"],
                                 f"status {r['status']} but no linked simulation case has all core results",
                                 "Link a simulation case with deformation, stress and strain results, or revert the status."))
    for r in _q(conn, """SELECT a.rev_label, a.product_id, b.rev_label sup, b.product_id sp FROM design_revision a
                         JOIN design_revision b ON b.rev_id = a.supersedes_rev_id WHERE a.product_id <> b.product_id"""):
        out.append(Issue("REVISION_CHAIN", "error", "design_revision", r["rev_label"], f"revision supersedes {r['sup']} of another product",
                         "A revision may only supersede a revision of the same product."))
    if any(_q(conn, f"SELECT 1 FROM {t} WHERE basis = 'demonstration' LIMIT 1") for t in ("part", "change_request", "design_revision")):
        out.append(Issue("DEMONSTRATION_DATA", "info", None, "BOM / revisions / change request",
                         "part numbers, BOM, design revisions and change requests are DEMONSTRATION data created by `python -m plm demo`, "
                         "not records of a real PLM system or a real approval", "Replace with real records if this is ever used operationally."))
    return out


def check_limitations(conn, root):
    out = [Issue("LIMITATION", "info", None, "validity of results",
                 "the repository holds no experimental data and no mesh-convergence study; the checks here test internal consistency and "
                 "comparability only and cannot show that the FEA results are physically correct",
                 "Add a mesh-convergence study and a hand calculation or test result before relying on the numbers."),
           Issue("LIMITATION", "info", None, "raw solver results",
                 "file.rst / SYS.mechdb are not parsed; stress, strain and deformation are documented values (README, report) cross-checked "
                 "against the solver monitor and mass, not re-extracted from the result file", "Parse the result file (e.g. with pyansys) to extract nodal results.")]
    if _q(conn, "SELECT COUNT(*) n FROM solver")[0]["n"] < 2:
        out.append(Issue("LIMITATION", "info", "solver", "cross-solver comparison",
                         "only one solver (ANSYS MAPDL) is present, so no cross-solver comparison is possible", "Add a second solver's results for the same configurations."))
    if _q(conn, "SELECT COUNT(DISTINCT value_num) n FROM simulation_input WHERE param_name = 'node_count'")[0]["n"] == 1:
        out.append(Issue("LIMITATION", "info", "simulation_input", "mesh sensitivity",
                         "all cases share one mesh size (same node/element counts), so mesh sensitivity of the results cannot be assessed",
                         "Run a mesh-convergence study (listed under Future Improvements in the README)."))
    return out


def check_sources(conn, root):
    """Source files on disk must still match what was imported (the README is a data source too)."""
    if root is None:
        return [Issue("SOURCE_FILE_CHANGED", "info", "source_file", "all files", "skipped: no repository root was given, so files were not re-hashed",
                      "Run validation with --root pointing at the repository.")]
    out = []
    for r in _q(conn, "SELECT source_file_id, rel_path, sha256 FROM source_file WHERE archive_member = ''"):
        path = Path(root) / r["rel_path"]
        if not path.is_file():
            out.append(Issue("SOURCE_FILE_CHANGED", "error", "source_file", r["rel_path"], "file recorded at import is missing on disk",
                             "Restore the file (git checkout) and re-run the import.", r["source_file_id"]))
        elif hashlib.sha256(path.read_bytes()).hexdigest() != r["sha256"]:
            out.append(Issue("SOURCE_FILE_CHANGED", "error", "source_file", r["rel_path"], "file content differs from the hash recorded at import",
                             "Re-run `init --force` and `import` so the database matches the files, or restore the original.", r["source_file_id"]))
    return out


def check_report_transcription(conn, root):
    """data/report_values.csv is a hand transcription: confirm every printed value appears on its cited PDF page."""
    if root is None:
        return []
    root = Path(root)
    pdfs = list((root / "Report").glob("*.pdf")) if (root / "Report").is_dir() else []
    csv_path = root / "data" / "report_values.csv"
    if not pdfs or not csv_path.is_file():
        return []
    if not shutil.which("pdftotext"):
        return [Issue("REPORT_TRANSCRIPTION", "info", "data/report_values.csv", "PDF cross-check skipped",
                      "pdftotext (poppler) is not installed, so the transcribed report values were not compared with the PDF",
                      "Install poppler-utils to enable this check.")]
    pages, out = {}, []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            page = int(row["pdf_page"])
            if page not in pages:
                text = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdfs[0]), "-"],
                                      capture_output=True, text=True).stdout
                pages[page] = re.sub(r"\s+", " ", text)
            needle = re.sub(r"\s+", " ", row["printed_value"].strip())
            if not re.search(r"(?<![\w.])" + re.escape(needle) + r"(?![\w])", pages[page]):
                out.append(Issue("REPORT_TRANSCRIPTION", "error", "data/report_values.csv", f"{row['subject']} {row['quantity']} p.{page}",
                                 f"printed value {needle!r} was not found on PDF page {page}", "Re-check the transcription against the PDF page."))
    return out


CHECKS = (check_integrity, check_required, check_duplicates, check_units, check_physical, check_links, check_comparability,
          check_cross_source, check_bom_and_workflow, check_limitations, check_sources, check_report_transcription)
_ORDER = {"error": 0, "warning": 1, "info": 2}


def run_checks(conn, root=None):
    """Run every check, store the run and its issues, and return (run_id, issues). Never modifies source data."""
    found = []
    for fn in CHECKS:
        try:
            found += fn(conn, root)
        except Exception as exc:  # corrupt data must produce a finding, never kill the whole validation run
            found.append(Issue("CHECK_ABORTED", "error", None, fn.__name__, f"{fn.__name__} aborted on this data: {type(exc).__name__}: {exc}",
                               "Inspect the data the check reads; this indicates malformed records or a bug in the check."))
    issues = sorted(found, key=lambda i: (_ORDER[i.severity], i.check_code, str(i.record_id)))
    n = {s: sum(i.severity == s for i in issues) for s in _ORDER}
    with conn:
        run_id = conn.execute("INSERT INTO validation_run(started_utc, n_error, n_warning, n_info) VALUES (?,?,?,?)",
                              (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), n["error"], n["warning"], n["info"])).lastrowid
        conn.executemany("INSERT INTO validation_issue(run_id, check_code, severity, table_name, record_id, source_file_id, message,"
                         " suggested_correction) VALUES (?,?,?,?,?,?,?,?)",
                         [(run_id, i.check_code, i.severity, i.table_name, i.record_id, i.source_file_id, i.message, i.suggested_correction) for i in issues])
    return run_id, issues
