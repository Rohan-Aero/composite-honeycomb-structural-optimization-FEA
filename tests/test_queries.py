"""Every documented SQL query runs and returns the expected results from the available data."""
import unittest

from plm import checks
from .support import ROOT, fresh_db

SQL = ROOT / "sql"


def run(conn, name):
    cur = conn.execute((SQL / name).read_text(encoding="utf-8"))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db(self)
        checks.run_checks(self.conn, ROOT)

    def test_every_sql_file_has_a_header_and_executes(self):
        files = sorted(SQL.glob("*.sql"))
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            text = f.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("-- query:"), f.name)
            self.assertIn("-- purpose:", text, f.name)
            self.assertIsInstance(run(self.conn, f.name), list)

    def test_compare_thickness_configs(self):
        rows = {r["config_code"]: r for r in run(self.conn, "01_compare_thickness_configs.sql")}
        self.assertEqual(list(rows), ["T085", "T120", "T160"])
        self.assertEqual(rows["T085"]["deformation_mm"], 0.0070107)
        self.assertEqual(rows["T085"]["deformation_change_pct_vs_baseline"], 0.0)
        self.assertEqual(rows["T120"]["deformation_change_pct_vs_baseline"], -14.29)   # (0.006009 - 0.0070107) / 0.0070107
        self.assertEqual(rows["T160"]["deformation_change_pct_vs_baseline"], -20.72)
        self.assertEqual(rows["T160"]["stress_change_pct_vs_baseline"], -4.55)
        self.assertEqual(rows["T160"]["strain_change_pct_vs_baseline"], -4.31)

    def test_rank_configurations_by_selected_metrics(self):
        rows = {r["config_code"]: r for r in run(self.conn, "02_rank_configurations.sql")}
        self.assertEqual([rows[c]["rank_lowest_deformation"] for c in ("T160", "T120", "T085")], [1, 2, 3])
        self.assertEqual(rows["T085"]["rank_lightest"], 1)
        self.assertEqual(rows["T120"]["rank_highest_specific_stiffness"], 1)           # 1.2 mm wins on stiffness per mass, not 1.6 mm
        self.assertAlmostEqual(rows["T160"]["stiffness_n_per_mm"], 1000 / 0.0055584, delta=1)
        self.assertAlmostEqual(rows["T160"]["specific_stiffness_n_per_mm_per_g"], 1000 / 0.0055584 / 52.999, places=1)

    def test_summary_by_solver_and_material(self):
        (row,) = run(self.conn, "03_summary_by_solver_material.sql")
        self.assertEqual((row["solver"], row["core_material"], row["face_sheet_material"], row["cases"]), ("ANSYS MAPDL 2025 R1", "PLA", "ePA-CF", 3))
        self.assertEqual((row["metrics_available"], row["metrics_missing"]), (24, 9))
        self.assertEqual((row["min_deformation_mm"], row["max_deformation_mm"]), (0.0055584, 0.0070107))

    def test_missing_data(self):
        rows = run(self.conn, "04_missing_data.sql")
        missing = [r for r in rows if r["availability"] == "MISSING"]
        self.assertEqual(len(missing), 9)
        self.assertEqual({r["item"] for r in missing}, {"directional_deformation", "strain_energy", "volume"})
        self.assertTrue(all(r["value"] is None for r in missing))
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("DELETE FROM result_metric WHERE case_id = 1 AND metric_name = 'equivalent_stress'")
        self.assertIn(("SIM-T085", "equivalent_stress"), {(r["record"], r["item"]) for r in run(self.conn, "04_missing_data.sql") if r["availability"] == "MISSING"})

    def test_quality_issues_query_reads_latest_run(self):
        rows = run(self.conn, "05_quality_issues.sql")
        self.assertEqual(rows[0]["severity"], "warning")                                # no errors, warnings sort first
        self.assertEqual(len(rows), self.conn.execute("SELECT n_error + n_warning + n_info FROM validation_run ORDER BY run_id DESC").fetchone()[0])

    def test_revision_tracking(self):
        rows = run(self.conn, "06_revision_tracking.sql")
        self.assertEqual([(r["rev_label"], r["config_code"], r["case_code"], r["ecr_code"]) for r in rows],
                         [("A", "T085", "SIM-T085", None), ("B", "T160", "SIM-T160", "DEMO-ECR-0001")])
        self.assertEqual(rows[1]["deformation_mm"], 0.0055584)
        self.assertTrue(all(r["project_saved_utc"].startswith("2025-04-29T") for r in rows))

    def test_cross_solver_comparison_is_empty_for_one_solver(self):
        self.assertEqual(run(self.conn, "07_cross_solver_comparison.sql"), [])

    def test_cross_solver_comparison_pairs_only_corresponding_results(self):
        # SYNTHETIC test data (never imported from the repository): a second solver with one result for T085.
        c = self.conn
        c.execute("INSERT INTO solver(name, version) VALUES ('SyntheticSolver', '0')")
        c.execute("INSERT INTO simulation_case(case_code, config_id, solver_id, analysis_type) "
                  "SELECT 'SYN-T085', config_id, (SELECT MAX(solver_id) FROM solver), 'STATIC (STEADY-STATE)' FROM configuration WHERE config_code = 'T085'")
        src = c.execute("SELECT source_file_id FROM source_file LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO result_metric(case_id, metric_name, statistic, value, unit, origin, source_file_id, locator) "
                  "VALUES ((SELECT case_id FROM simulation_case WHERE case_code = 'SYN-T085'), 'total_deformation', 'max', 0.0071107, 'mm', 'documented', ?, 'synthetic')", (src,))
        c.execute("INSERT INTO result_metric(case_id, metric_name, statistic, value, unit, origin, source_file_id, locator) "
                  "VALUES ((SELECT case_id FROM simulation_case WHERE case_code = 'SYN-T085'), 'volume', 'max', 1.0, 'mm^3', 'documented', ?, 'synthetic')", (src,))
        rows = run(c, "07_cross_solver_comparison.sql")
        self.assertEqual(len(rows), 1)                                                  # volume has no counterpart in the other solver
        self.assertEqual((rows[0]["config_code"], rows[0]["metric_name"]), ("T085", "total_deformation"))
        self.assertAlmostEqual(rows[0]["difference_pct_b_vs_a"], 1.426, places=3)       # (0.0071107 - 0.0070107) / 0.0070107

    def test_traceability_rows_all_have_source_and_locator(self):
        rows = run(self.conn, "08_traceability.sql")
        self.assertGreater(len(rows), 100)
        self.assertTrue(all(r["source_file"] and r["locator"] and len(r["sha256"]) == 64 for r in rows))
        self.assertEqual({r["config_code"] for r in rows}, {"T085", "T120", "T160"})
        self.assertEqual({r["origin"] for r in rows}, {"solver_file", "documented", "derived"})

    def test_bom_query_rolls_up_quantities(self):
        rows = [r for r in run(self.conn, "09_bom_by_configuration.sql") if r["config_code"] == "T120"]
        self.assertEqual([(r["part_number"].strip(), r["quantity_per_assembly"]) for r in rows],
                         [("DEMO-HSP-1000", 1.0), ("DEMO-HSP-2000", 1.0), ("DEMO-HSP-3120", 2.0)])
        self.assertTrue(rows[1]["part_number"].startswith("  "))                         # indented below the assembly

    def test_change_request_queries(self):
        rows = run(self.conn, "10_change_requests.sql")
        verification = {r["item"]: r["deformation_mm"] for r in rows if r["role"] == "verification"}
        self.assertEqual(verification, {"SIM-T085": 0.0070107, "SIM-T160": 0.0055584})
        self.assertEqual({r["status"] for r in rows}, {"VERIFIED"})
        history = run(self.conn, "11_change_request_history.sql")
        self.assertEqual([r["to_status"] for r in history], ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "IMPLEMENTED", "VERIFIED"])

    def test_queries_run_from_the_sqlite_command_line_style(self):
        # `sqlite3 db < file.sql` executes the file as a script; the same must work through executescript
        for f in sorted(SQL.glob("*.sql")):
            self.conn.executescript(f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
