"""PLM-style workflows: BOM, design revisions and engineering change requests (ECR).

EVERYTHING created here is DEMONSTRATION data (basis = 'demonstration'): illustrative part numbers, a BOM derived from the
three bodies of the ANSYS model, and a simulated change request. It is not an enterprise PLM deployment and nothing in it
is, or claims to be, approved by a real organisation (no approval authority is modelled).
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from . import checks
from .checks import CORE_METRICS, Issue
from .ingest import ImportRejected

ROOT = Path(__file__).resolve().parent.parent
DEMO_BOM_CSV = "data/demo_bom.csv"
ECR_TRANSITIONS = {
    "DRAFT": ("SUBMITTED", "REJECTED"),
    "SUBMITTED": ("UNDER_REVIEW", "REJECTED"),
    "UNDER_REVIEW": ("IMPLEMENTED", "REJECTED"),
    "IMPLEMENTED": ("VERIFIED", "REJECTED"),
    "VERIFIED": ("CLOSED",),
    "CLOSED": (),
    "REJECTED": (),
}


class WorkflowError(Exception):
    """A workflow rule was violated; nothing was changed."""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one(conn, sql, params, what):
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise WorkflowError(f"unknown {what}: {params[0]!r}")
    return row[0]


# ------------------------------------------------------------------ BOM
def import_demo_bom(conn, path):
    """Load the (demonstration) BOM CSV. Rows with errors reject the whole file; nothing is repaired."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = [(reader.line_num, r) for r in reader]
    label = Path(path).name
    issues = checks.check_csv_rows(rows, label, required=("config_code", "part_number", "part_name", "part_type", "quantity"),
                                   numeric=("quantity", "find_no", "thickness_mm"),
                                   enums={"part_type": {"assembly", "component"}},
                                   key=("config_code", "parent_part_number", "part_number"))
    if issues:
        raise ImportRejected(issues)
    configs = {r[0]: r[1] for r in conn.execute("SELECT config_code, config_id FROM configuration")}
    materials = {r[0].lower(): r[1] for r in conn.execute("SELECT name, material_id FROM material")}
    parts, spelled, bad = {}, {}, []
    for line, r in rows:
        where = f"{label} line {line}"
        if r["config_code"] not in configs:
            bad.append(Issue("BOM_UNKNOWN_CONFIG", "error", label, where, f"unknown configuration {r['config_code']!r}", "Use an existing configuration code."))
        if r["material"].strip() and r["material"].strip().lower() not in materials:
            bad.append(Issue("BOM_UNKNOWN_MATERIAL", "error", label, where, f"unknown material {r['material']!r}", "Use a material that exists in the database."))
        if float(r["quantity"]) <= 0:
            bad.append(Issue("BOM_BAD_QUANTITY", "error", label, where, f"quantity {r['quantity']} must be positive", "Correct the quantity."))
        key = re.sub(r"[\s\-_]", "", r["part_number"]).upper()
        if spelled.setdefault(key, r["part_number"]) != r["part_number"]:
            bad.append(Issue("DUPLICATE_PART_NUMBER", "error", label, where, f"part number {r['part_number']!r} duplicates {spelled[key]!r} (different spelling)",
                             "Use one spelling per part number."))
        definition = (r["part_name"], r["part_type"], r["material"], r["thickness_mm"])
        if parts.setdefault(r["part_number"], definition) != definition:
            bad.append(Issue("BOM_CONFLICTING_PART", "error", label, where, f"{r['part_number']} is defined differently on another line",
                             "A part number must have one name, type, material and thickness."))
        if r["parent_part_number"] and not any(x["part_number"] == r["parent_part_number"] and x["config_code"] == r["config_code"] for _, x in rows):
            bad.append(Issue("BOM_UNKNOWN_PARENT", "error", label, where, f"parent {r['parent_part_number']!r} is not a line of configuration {r['config_code']}",
                             "Add the parent line or correct the parent part number."))
    if bad:
        raise ImportRejected(bad)
    with conn:
        ids = {}
        for number, (name, ptype, material, thickness) in parts.items():
            ids[number] = conn.execute("INSERT INTO part(part_number, name, part_type, material_id, thickness_mm, basis) VALUES (?,?,?,?,?, 'demonstration')",
                                       (number, name, ptype, materials.get(material.strip().lower()), float(thickness) if thickness.strip() else None)).lastrowid
        for _line, r in rows:
            if r["parent_part_number"]:
                conn.execute("INSERT INTO bom_line(config_id, parent_part_id, child_part_id, quantity, find_no) VALUES (?,?,?,?,?)",
                             (configs[r["config_code"]], ids[r["parent_part_number"]], ids[r["part_number"]], float(r["quantity"]),
                              int(float(r["find_no"])) if r["find_no"].strip() else None))


# ------------------------------------------------------------------ change requests and revisions
def create_ecr(conn, code, title, reason, items):
    """items: [(role, kind, reference, note)]; kind = part (part number) | config (config code) | case (case code)."""
    column = {"part": ("part_id", "SELECT part_id FROM part WHERE part_number = ?"),
              "config": ("config_id", "SELECT config_id FROM configuration WHERE config_code = ?"),
              "case": ("case_id", "SELECT case_id FROM simulation_case WHERE case_code = ?")}
    with conn:
        ecr = conn.execute("INSERT INTO change_request(ecr_code, title, reason, status, basis) VALUES (?,?,?, 'DRAFT', 'demonstration')",
                           (code, title, reason)).lastrowid
        conn.execute("INSERT INTO ecr_status_history(ecr_id, seq, from_status, to_status, changed_utc, note) VALUES (?,1,NULL,'DRAFT',?,?)",
                     (ecr, _now(), "created"))
        for role, kind, ref, note in items:
            col, sql = column[kind]
            conn.execute(f"INSERT INTO ecr_item(ecr_id, role, {col}, note) VALUES (?,?,?,?)", (ecr, role, _one(conn, sql, (ref,), kind), note))
    return ecr


def release_revision(conn, product_code, rev_label, config_code, ecr_code=None, supersedes=None, description=None):
    product = _one(conn, "SELECT product_id FROM product WHERE product_code = ?", (product_code,), "product")
    config = _one(conn, "SELECT config_id FROM configuration WHERE config_code = ?", (config_code,), "configuration")
    ecr = sup = None
    if ecr_code:
        ecr = _one(conn, "SELECT ecr_id FROM change_request WHERE ecr_code = ?", (ecr_code,), "change request")
        if not conn.execute("SELECT 1 FROM ecr_item WHERE ecr_id = ? AND role = 'proposed' AND config_id = ?", (ecr, config)).fetchone():
            raise WorkflowError(f"configuration {config_code} is not a proposed configuration of {ecr_code}")
    if supersedes:
        sup = _one(conn, "SELECT rev_id FROM design_revision WHERE product_id = ? AND rev_label = ?", (product, supersedes), "revision")
    try:
        with conn:
            return conn.execute("INSERT INTO design_revision(product_id, rev_label, config_id, ecr_id, supersedes_rev_id, description, basis)"
                                " VALUES (?,?,?,?,?,?, 'demonstration')", (product, rev_label, config, ecr, sup, description)).lastrowid
    except Exception as exc:  # sqlite3.IntegrityError for a duplicate label
        raise WorkflowError(f"revision {rev_label} cannot be created: {exc}") from exc


def _gate(conn, ecr, target):
    """Rules a change request must satisfy before entering `target`."""
    if target == "SUBMITTED" and not conn.execute("SELECT 1 FROM ecr_item WHERE ecr_id = ? AND role IN ('affected','proposed')", (ecr,)).fetchone():
        raise WorkflowError("cannot submit: no affected or proposed item is listed")
    if target == "IMPLEMENTED" and not conn.execute("SELECT 1 FROM design_revision WHERE ecr_id = ?", (ecr,)).fetchone():
        raise WorkflowError("cannot mark implemented: no design revision references this change request")
    if target == "VERIFIED":
        for (config,) in conn.execute("SELECT config_id FROM ecr_item WHERE ecr_id = ? AND role = 'proposed' AND config_id IS NOT NULL", (ecr,)).fetchall():
            ok = False
            for (case,) in conn.execute("SELECT i.case_id FROM ecr_item i JOIN simulation_case c USING(case_id) WHERE i.ecr_id = ? AND i.role = 'verification'"
                                        " AND c.config_id = ?", (ecr, config)).fetchall():
                have = {r[0] for r in conn.execute("SELECT metric_name FROM v_result_primary WHERE case_id = ?", (case,))}
                ok = ok or set(CORE_METRICS) <= have
            if not ok:
                raise WorkflowError("cannot verify: a proposed configuration has no linked simulation case with deformation, stress and strain results")


def transition(conn, ecr_code, new_status, note=None):
    ecr = _one(conn, "SELECT ecr_id FROM change_request WHERE ecr_code = ?", (ecr_code,), "change request")
    current = conn.execute("SELECT status FROM change_request WHERE ecr_id = ?", (ecr,)).fetchone()[0]
    if new_status not in ECR_TRANSITIONS.get(current, ()):
        raise WorkflowError(f"illegal transition {current} -> {new_status}; allowed: {list(ECR_TRANSITIONS.get(current, ())) or 'none'}")
    _gate(conn, ecr, new_status)
    with conn:
        conn.execute("UPDATE change_request SET status = ? WHERE ecr_id = ?", (new_status, ecr))
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM ecr_status_history WHERE ecr_id = ?", (ecr,)).fetchone()[0]
        conn.execute("INSERT INTO ecr_status_history(ecr_id, seq, from_status, to_status, changed_utc, note) VALUES (?,?,?,?,?,?)",
                     (ecr, seq, current, new_status, _now(), note))


def seed_demo(conn, root=ROOT):
    """Build the demonstration BOM, two revisions and one change request linked to the real simulation results."""
    import_demo_bom(conn, Path(root) / DEMO_BOM_CSV)
    release_revision(conn, "HSP", "A", "T085", description="DEMONSTRATION baseline: thinnest face sheet of the parametric study")
    create_ecr(conn, "DEMO-ECR-0001", "Increase face-sheet thickness from 0.85 mm to 1.6 mm",
               "DEMONSTRATION: reduce the maximum total deformation under the 1000 N study load, using the parametric-study "
               "results already in the database as evidence. Simulated workflow; no real approval is implied.",
               [("affected", "part", "DEMO-HSP-3085", "face sheet being replaced"), ("proposed", "part", "DEMO-HSP-3160", "thicker face sheet"),
                ("affected", "config", "T085", "baseline configuration"), ("proposed", "config", "T160", "proposed configuration"),
                ("verification", "case", "SIM-T085", "baseline result for comparison"), ("verification", "case", "SIM-T160", "result of the proposed configuration")])
    transition(conn, "DEMO-ECR-0001", "SUBMITTED", "demonstration step")
    transition(conn, "DEMO-ECR-0001", "UNDER_REVIEW", "demonstration step (no real reviewer)")
    release_revision(conn, "HSP", "B", "T160", "DEMO-ECR-0001", "A", "DEMONSTRATION revision implementing DEMO-ECR-0001")
    transition(conn, "DEMO-ECR-0001", "IMPLEMENTED", "revision B created")
    transition(conn, "DEMO-ECR-0001", "VERIFIED", "verification evidence linked: SIM-T085 and SIM-T160 core results exist (see engineering report for the derived comparison)")
