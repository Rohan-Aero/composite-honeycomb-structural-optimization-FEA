"""Generate the engineering report, the data-quality report, query CSVs and SVG charts from the database.

Everything is plain text (Markdown / CSV / SVG, standard library only). Source values, derived values and
demonstration data are labelled separately; the report never edits the database.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from xml.sax.saxutils import escape

from . import checks

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
SOURCE_BLUE, DERIVED_ORANGE = "#2a6fb0", "#c26a14"


# ------------------------------------------------------------------ queries
def run_queries(conn, sql_dir=SQL_DIR):
    """Execute every sql/*.sql file. Returns {stem: {'title', 'notes', 'columns', 'rows'}} in file order."""
    out = {}
    for path in sorted(Path(sql_dir).glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        header = [l[3:].strip() for l in text.splitlines() if l.startswith("-- ")]
        title = next((h[6:].strip() for h in header if h.startswith("title:")), path.stem)
        cur = conn.execute(text)
        out[path.stem] = {"title": title, "notes": [h for h in header if not h.startswith(("query:", "title:", "usage:"))],
                          "columns": [d[0] for d in cur.description], "rows": [tuple(r) for r in cur.fetchall()]}
    return out


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v).replace("|", "\\|").replace("\n", " ")


def md_table(columns, rows):
    if not rows:
        return "_no rows_\n"
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    lines += ["| " + " | ".join(_cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        w.writerows([["" if v is None else v for v in r] for r in rows])


# ------------------------------------------------------------------ charts (plain SVG, zero-based bars)
def _nice_step(raw):
    base = 10 ** math.floor(math.log10(raw))
    return next(m * base for m in (1, 2, 2.5, 5, 10) if m * base >= raw)


def _tick(v):
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.3g}"


def bar_chart(path, title, subtitle, labels, values, unit, color):
    W, H, L, R, T, B = 360, 250, 70, 16, 56, 44
    step = _nice_step(max(values) * 1.1 / 4)
    top = step * math.ceil(max(values) * 1.05 / step)
    y = lambda v: T + (H - T - B) * (1 - v / top)
    bw = (W - L - R) / len(values)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
             f'aria-labelledby="t d" font-family="Helvetica, Arial, sans-serif" font-size="11">',
             f'<title id="t">{escape(title)}</title><desc id="d">{escape(subtitle)}. Values: '
             + "; ".join(f"{l} = {v:.5g} {unit}" for l, v in zip(labels, values)) + '</desc>',
             f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
             f'<text x="{L}" y="20" font-size="13" font-weight="bold" fill="#1a1a1a">{escape(title)}</text>',
             f'<text x="{L}" y="36" fill="#555555">{escape(subtitle)}</text>']
    for k in range(int(round(top / step)) + 1):
        v = k * step
        parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#dddddd"/>'
                     f'<text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end" fill="#444444">{_tick(v)}</text>')
    for i, (lab, v) in enumerate(zip(labels, values)):
        x = L + i * bw + bw * 0.2
        parts.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{bw * 0.6:.1f}" height="{y(0) - y(v):.1f}" fill="{color}"/>'
                     f'<text x="{x + bw * 0.3:.1f}" y="{y(v) - 5:.1f}" text-anchor="middle" fill="#1a1a1a">{v:.5g}</text>'
                     f'<text x="{x + bw * 0.3:.1f}" y="{H - B + 16}" text-anchor="middle" fill="#444444">{escape(lab)}</text>')
    parts.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 6}" text-anchor="middle" fill="#444444">face-sheet thickness; axis unit: {escape(unit)}</text></svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def make_charts(results, out_dir):
    """Charts from queries 01 (documented results) and 02 (mass, derived specific stiffness)."""
    q1, q2 = results["01_compare_thickness_configs"], results["02_rank_configurations"]
    c1, c2 = {n: i for i, n in enumerate(q1["columns"])}, {n: i for i, n in enumerate(q2["columns"])}
    labels = [f"{r[c1['thickness_mm']]:g} mm" for r in q1["rows"]]
    by_thickness = sorted(q2["rows"], key=lambda r: r[c2["thickness_mm"]])
    specs = [("total_deformation", "Maximum total deformation", "SOURCE: documented ANSYS result", [r[c1["deformation_mm"]] for r in q1["rows"]], "mm", SOURCE_BLUE),
             ("equivalent_stress", "Maximum equivalent (von Mises) stress", "SOURCE: documented ANSYS result", [r[c1["stress_mpa"]] for r in q1["rows"]], "MPa", SOURCE_BLUE),
             ("equivalent_elastic_strain", "Maximum equivalent elastic strain", "SOURCE: documented ANSYS result", [r[c1["strain"]] for r in q1["rows"]], "-", SOURCE_BLUE),
             ("total_mass", "Total model mass", "SOURCE: ANSYS solver mass summary", [r[c2["mass_g"]] for r in by_thickness], "g", SOURCE_BLUE),
             ("specific_stiffness", "Specific stiffness proxy", "DERIVED: F/(deformation x mass), equal load, indicative",
              [r[c2["specific_stiffness_n_per_mm_per_g"]] for r in by_thickness], "N/mm/g", DERIVED_ORANGE)]
    files = []
    for stem, title, subtitle, values, unit, color in specs:
        if values and all(v is not None for v in values):
            bar_chart(Path(out_dir) / f"{stem}_by_thickness.svg", title, subtitle, labels, values, unit, color)
            files.append((stem, title, subtitle))
    return files


# ------------------------------------------------------------------ data-quality report
def _latest_issues(conn):
    run = conn.execute("SELECT * FROM validation_run ORDER BY run_id DESC LIMIT 1").fetchone()
    if run is None:
        raise RuntimeError("no validation run found; run `python -m plm validate` first")
    issues = conn.execute("""SELECT i.severity, i.check_code, i.table_name, i.record_id, i.message, i.suggested_correction, sf.rel_path
                             FROM validation_issue i LEFT JOIN source_file sf USING (source_file_id) WHERE i.run_id = ?
                             ORDER BY CASE i.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, i.check_code, i.record_id""",
                          (run["run_id"],)).fetchall()
    return run, issues


def data_quality_report(conn, out_dir):
    _run, issues = _latest_issues(conn)
    out_dir = Path(out_dir)
    write_csv(out_dir / "data_quality_report.csv", ["severity", "check_code", "table", "affected_record", "issue", "suggested_correction", "source_file"],
              [tuple(r) for r in issues])
    counts = {s: sum(r["severity"] == s for r in issues) for s in ("error", "warning", "info")}
    by_code = {}
    for r in issues:
        by_code.setdefault(r["check_code"], {}).setdefault(r["severity"], 0)
        by_code[r["check_code"]][r["severity"]] += 1
    md = ["# Data-quality report", "",
          f"**{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} information item(s).**", "",
          "* **error**: the data is wrong or unusable as it stands.",
          "* **warning**: an inconsistency or comparability problem a person must resolve; the data stays usable.",
          "* **info**: a limitation or missing optional data worth knowing about.", "",
          "> A passing check only shows that data is internally consistent. It does **not** show that the FEA results are physically valid: the repository "
          "contains no experimental data and no mesh-convergence study. Source files are never modified; every finding below is reported, not fixed.", "",
          "## Checks executed", "", "| Check | Verifies | Result |", "|---|---|---|"]
    for code, text in checks.CODES.items():
        found = by_code.get(code)
        md.append(f"| `{code}` | {text} | " + (", ".join(f"{n} {s}" for s, n in found.items()) if found else "pass") + " |")
    md += ["", "## Findings", ""]
    for sev in ("error", "warning", "info"):
        rows = [r for r in issues if r["severity"] == sev]
        md += [f"### {sev.capitalize()} ({len(rows)})", ""]
        if rows:
            md.append(md_table(["Check", "Affected record", "Issue", "Suggested correction"],
                               [(r["check_code"], r["record_id"], r["message"], r["suggested_correction"]) for r in rows]))
        else:
            md.append("_none_\n")
    (out_dir / "data_quality_report.md").write_text("\n".join(md), encoding="utf-8")
    return counts


# ------------------------------------------------------------------ engineering report
def engineering_report(conn, results, charts, out_dir):
    out_dir = Path(out_dir)
    n = lambda sql: conn.execute(sql).fetchone()[0]
    counts = {"configurations": n("SELECT COUNT(*) FROM configuration"), "simulation cases": n("SELECT COUNT(*) FROM simulation_case"),
              "source files registered": n("SELECT COUNT(*) FROM source_file"), "result values": n("SELECT COUNT(*) FROM result_metric WHERE status='ok'"),
              "results marked missing": n("SELECT COUNT(*) FROM result_metric WHERE status='missing'"),
              "solver inputs / BCs": n("SELECT COUNT(*) FROM simulation_input")}
    _run, issues = _latest_issues(conn)
    sev = {s: sum(r["severity"] == s for r in issues) for s in ("error", "warning", "info")}

    def section(stem, level="##", only=None, note=""):
        r = results[stem]
        rows = [x for x in r["rows"] if only is None or only(dict(zip(r["columns"], x)))]
        return [f"{level} {r['title']}", ""] + ([note, ""] if note else []) + [md_table(r["columns"], rows), f"_Query: `sql/{stem}.sql`; full output: `query_outputs/{stem}.csv`._", ""]

    md = ["# Engineering data report: honeycomb sandwich panel", "",
          "Generated from the SQLite database built from this repository. **Three kinds of data are kept apart:**", "",
          "* **SOURCE** - values imported unchanged from repository files (README, report PDF, ANSYS archives), each traceable to a file and locator.",
          "* **DERIVED** - calculated by the queries from source values (percent changes, stiffness proxy). They are labelled and never stored as results.",
          "* **DEMONSTRATION** - illustrative BOM, revisions and change request created by `python -m plm demo`. Not records of a real PLM system, "
          "and nothing was approved by any organisation.", "",
          "## Dataset overview", "", md_table(["item", "count"], list(counts.items())),
          f"Data-quality run: {sev['error']} error(s), {sev['warning']} warning(s), {sev['info']} information item(s); see `data_quality_report.md`.", ""]
    md += section("01_compare_thickness_configs", note="SOURCE values (documented ANSYS results) with DERIVED percent changes versus the thinnest face sheet.")
    for stem, title, subtitle in charts:
        md.append(f"![{title}: {subtitle}](charts/{stem}_by_thickness.svg)")
    md += [""]
    r2 = results["02_rank_configurations"]
    ci2 = {c: i for i, c in enumerate(r2["columns"])}
    winners = "; ".join(f"{c[5:].replace('_', ' ')}: {next(r[ci2['config_code']] for r in r2['rows'] if r[i] == 1)}"
                        for c, i in ci2.items() if c.startswith("rank_") and any(r[i] == 1 for r in r2["rows"]))
    md += section("02_rank_configurations", note=f"Rank 1 = best for that metric. **DERIVED** columns: stiffness and specific stiffness. Rank-1 configuration "
                  f"per metric - {winners}. Different metrics can pick different winners, so 'optimal' depends on the objective.")
    md += section("03_summary_by_solver_material")
    md += section("04_missing_data", only=lambda r: r["availability"] == "MISSING",
                  note="Values that exist only in the binary result file or as contour images are marked missing, never estimated.")
    md += section("07_cross_solver_comparison", note="Only results that exist for the same configuration, analysis type, metric and component in two solvers are "
                  "compared. The repository contains a single solver, so no cross-solver comparison is possible and the result is empty by design.")
    md += ["## DEMONSTRATION data: BOM, revisions and change request", "",
           "> Everything in this section is illustrative. Part numbers use the `DEMO-` prefix. The BOM mirrors the three bodies of the ANSYS model; "
           "the revisions and the change request are a simulated workflow linked to the real simulation results above.", ""]
    md += section("09_bom_by_configuration", level="###") + section("06_revision_tracking", level="###") \
        + section("10_change_requests", level="###") + section("11_change_request_history", level="###")
    # traceability: one configuration as a worked example, full output as CSV
    t = results["08_traceability"]
    ci = {c: i for i, c in enumerate(t["columns"])}
    example = [(r[ci["item"]], r[ci["value"]], r[ci["unit"]], r[ci["origin"]], r[ci["source_file"]].split("/")[-1] + (" :: " + r[ci["archive_member"]].split("/")[-1] if r[ci["archive_member"]] else ""),
                r[ci["locator"]], r[ci["sha256"]][:12]) for r in t["rows"]
               if r[ci["config_code"]] == "T085" and r[ci["kind"]] == "result" and r[ci["item"]].split(" ")[0] in
               ("total_deformation", "equivalent_stress", "equivalent_elastic_strain", "total_mass", "max_displacement_component")]
    md += ["## Traceability example (configuration T085)", "",
           "Every value links to its source file, archive member, line/table locator and SHA-256 (first 12 characters shown). `08_traceability.csv` "
           "lists all inputs, results and material properties for all configurations.", "",
           md_table(["item", "value", "unit", "origin", "source file", "locator", "sha256"], example), ""]
    md += ["## Limitations", ""] + [f"* {r['message']}" for r in issues if r["check_code"] == "LIMITATION"] + [""]
    (out_dir / "engineering_report.md").write_text("\n".join(md), encoding="utf-8")


def generate(conn, out_dir="generated_reports", sql_dir=SQL_DIR):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = run_queries(conn, sql_dir)
    charts = make_charts(results, out_dir / "charts")
    counts = data_quality_report(conn, out_dir)
    engineering_report(conn, results, charts, out_dir)
    for stem, r in results.items():
        write_csv(out_dir / "query_outputs" / f"{stem}.csv", r["columns"], r["rows"])
    return counts
