"""Command line: python -m plm {init,import,demo,validate,query,report,all}"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import checks, db, ingest, report, workflow

ROOT = Path(__file__).resolve().parent.parent


def _print_issues(issues, stream=None):
    stream = stream or sys.stderr
    for i in issues:
        print(f"  [{i.severity}] {i.check_code}: {i.message}  ({i.record_id})", file=stream)


def _validate(conn, root):
    run_id, issues = checks.run_checks(conn, root)
    n = {s: sum(i.severity == s for i in issues) for s in ("error", "warning", "info")}
    print(f"validate: {n['error']} error(s), {n['warning']} warning(s), {n['info']} info (run {run_id})")
    _print_issues([i for i in issues if i.severity != "info"], sys.stdout)
    return n["error"]


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)  # --db/--root are accepted before or after the sub-command
    common.add_argument("--db", default=argparse.SUPPRESS, help="SQLite database file (default: build/honeycomb_plm.sqlite)")
    common.add_argument("--root", default=argparse.SUPPRESS, help="repository root holding the source files (default: this repository)")
    ap = argparse.ArgumentParser(prog="python -m plm", description="PLM-inspired engineering data management for the honeycomb FEA project",
                                 parents=[common])
    ap.set_defaults(db=str(ROOT / "build" / "honeycomb_plm.sqlite"), root=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", parents=[common], help="create an empty database from schema.sql")
    p.add_argument("--force", action="store_true", help="replace an existing database file (it is a derived artifact)")
    sub.add_parser("import", parents=[common], help="import ANSYS project data, README and report values (read-only on the sources)")
    sub.add_parser("demo", parents=[common], help="load the DEMONSTRATION BOM, revisions and change request")
    sub.add_parser("validate", parents=[common], help="run the data-quality checks (exit status 1 if any error)")
    p = sub.add_parser("query", parents=[common], help="run one SQL file (e.g. sql/01_compare_thickness_configs.sql) and print the result")
    p.add_argument("sql_file")
    p = sub.add_parser("report", parents=[common], help="write SQL outputs, charts and the engineering / data-quality reports")
    p.add_argument("--out", default=str(ROOT / "generated_reports"), help="output directory (default: generated_reports/)")
    p = sub.add_parser("all", parents=[common], help="init --force, import, demo, validate and report in one go")
    p.add_argument("--out", default=str(ROOT / "generated_reports"))
    args = ap.parse_args(argv)
    root = Path(args.root)
    conn = None
    try:
        if args.cmd in ("init", "all"):
            conn = db.init_db(args.db, force=args.cmd == "all" or args.force)
            print(f"init: created {args.db}")
        else:
            if not Path(args.db).exists():
                print(f"error: {args.db} does not exist; run `python -m plm init` first", file=sys.stderr)
                return 2
            conn = db.connect(args.db)
        if args.cmd in ("import", "all"):
            ingest.import_all(conn, root)
            c = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"import: {c('configuration')} configurations, {c('simulation_case')} cases, {c('result_metric')} results, "
                  f"{c('simulation_input')} inputs, {c('source_file')} source files registered")
        if args.cmd == "query":
            cur = conn.execute(Path(args.sql_file).read_text(encoding="utf-8"))
            print(report.md_table([d[0] for d in cur.description], cur.fetchall()))
        if args.cmd in ("demo", "all"):
            workflow.seed_demo(conn, root)
            print("demo: loaded DEMONSTRATION BOM, revisions A/B and DEMO-ECR-0001")
        status = 0
        if args.cmd in ("validate", "all"):
            status = 1 if _validate(conn, root) else 0
        if args.cmd in ("report", "all"):
            counts = report.generate(conn, args.out, ROOT / "sql")
            print(f"report: written to {args.out} ({counts['error']} error, {counts['warning']} warning, {counts['info']} info in the data-quality report)")
        return status
    except ingest.ImportRejected as exc:
        print("import rejected; nothing was changed:", file=sys.stderr)
        _print_issues(exc.issues)
        return 2
    except (FileExistsError, workflow.WorkflowError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            conn.close()
