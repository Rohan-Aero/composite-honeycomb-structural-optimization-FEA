import contextlib
import csv
import hashlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from plm import cli, db, ingest
from .support import ROOT, fresh_db, member_sha, source_hashes


def quiet_main(argv):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return cli.main(argv)


class CleanBuildTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db(self)

    def one(self, sql, *params):
        return self.conn.execute(sql, params).fetchone()[0]

    def test_init_from_clean_state_creates_schema(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        conn = db.init_db(tmp / "x.sqlite")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("project", "product", "configuration", "part", "bom_line", "design_revision", "change_request", "ecr_item",
                  "simulation_case", "solver", "simulation_input", "result_metric", "material_property", "source_file",
                  "artifact_link", "validation_run", "validation_issue"):
            self.assertIn(t, tables)
        conn.close()
        with self.assertRaises(FileExistsError):  # never silently replaces an existing database
            db.init_db(tmp / "x.sqlite")
        db.init_db(tmp / "x.sqlite", force=True).close()

    def test_expected_counts_and_source_values(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM configuration"), 3)
        self.assertEqual(self.one("SELECT COUNT(*) FROM simulation_case"), 3)
        self.assertEqual(self.one("SELECT COUNT(*) FROM result_metric WHERE status = 'missing'"), 9)
        get = lambda case, metric, comp="assembly": self.one(
            "SELECT value FROM v_result_primary p JOIN simulation_case c USING (case_id) WHERE c.case_code = ? AND metric_name = ? AND component = ?",
            case, metric, comp)
        self.assertEqual(get("SIM-T085", "total_deformation"), 0.0070107)   # report Table 6 beats the rounded README value
        self.assertEqual(get("SIM-T160", "total_deformation"), 0.0055584)
        self.assertEqual(get("SIM-T120", "equivalent_stress"), 2.9189)       # Pa in the report, MPa in the database
        self.assertEqual(get("SIM-T085", "equivalent_elastic_strain"), 0.00089581)
        self.assertEqual(get("SIM-T085", "total_mass"), 41.041)              # solver tonne -> g
        self.assertAlmostEqual(get("SIM-T160", "element_type_mass", "face_sheet_1"), 12.7555, places=4)
        self.assertEqual(self.one("SELECT name || ' ' || version FROM solver"), "ANSYS MAPDL 2025 R1")

    def test_derived_load_equals_report_load(self):
        for case in ("SIM-T085", "SIM-T120", "SIM-T160"):
            force = self.one("SELECT value_num FROM simulation_input i JOIN simulation_case c USING (case_id) "
                             "WHERE c.case_code = ? AND param_name = 'applied_force' AND origin = 'derived'", case)
            self.assertAlmostEqual(force, 1000.0, places=3)

    def test_original_value_and_unit_are_kept_next_to_converted_value(self):
        r = self.conn.execute("SELECT value, unit, original_value, original_unit, printed_text FROM result_metric r JOIN source_file s USING (source_file_id) "
                              "WHERE s.file_kind = 'report_pdf' AND metric_name = 'equivalent_stress' AND case_id = 1").fetchone()
        self.assertEqual((r["value"], r["unit"], r["original_value"], r["original_unit"]), (2.9896, "MPa", 2989600.0, "Pa"))
        self.assertIn("10", r["printed_text"])

    def test_missing_values_are_marked_not_invented(self):
        rows = self.conn.execute("SELECT metric_name, value, missing_reason FROM result_metric WHERE status = 'missing'").fetchall()
        self.assertEqual({r["metric_name"] for r in rows}, {"directional_deformation", "strain_energy", "volume"})
        self.assertTrue(all(r["value"] is None and r["missing_reason"] for r in rows))

    def test_no_foreign_key_violations(self):
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_import_twice_is_rejected(self):
        with self.assertRaises(ingest.ImportRejected) as ctx:
            ingest.import_all(self.conn, ROOT)
        self.assertEqual(ctx.exception.issues[0].check_code, "IMPORT_ALREADY_DONE")


class TraceabilityTests(unittest.TestCase):
    def test_every_imported_value_points_to_a_real_file_with_matching_hash(self):
        conn = fresh_db(self)
        for table in ("result_metric", "simulation_input", "material_property"):
            rows = conn.execute(f"SELECT t.locator, s.rel_path, s.archive_member, s.sha256 FROM {table} t JOIN source_file s USING (source_file_id)").fetchall()
            self.assertGreater(len(rows), 0)
            for r in rows:
                self.assertTrue(r["locator"])
                self.assertTrue((ROOT / r["rel_path"]).is_file(), r["rel_path"])
                if r["archive_member"]:
                    self.assertEqual(member_sha(r["rel_path"], r["archive_member"]), r["sha256"])
                else:
                    self.assertEqual(hashlib.sha256((ROOT / r["rel_path"]).read_bytes()).hexdigest(), r["sha256"])

    def test_configuration_traces_to_inputs_outputs_and_files(self):
        conn = fresh_db(self)
        roles = {r[0] for r in conn.execute("SELECT role FROM artifact_link l JOIN configuration c USING (config_id) WHERE c.config_code = 'T085'")}
        for needed in ("solver_input_deck", "solver_log", "solver_monitor", "workbench_archive", "geometry_cad", "report_pdf", "readme",
                       "contour_image:total_deformation", "contour_image:equivalent_stress"):
            self.assertIn(needed, roles)


class SourceIntegrityTests(unittest.TestCase):
    def test_pipeline_does_not_modify_source_files(self):
        before = source_hashes()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        status = quiet_main(["all", "--db", str(tmp / "p.sqlite"), "--out", str(tmp / "rep")])
        self.assertEqual(status, 0)
        self.assertEqual(source_hashes(), before)
        self.assertTrue((tmp / "rep" / "engineering_report.md").is_file())

    def test_cli_steps_work_separately_and_validate_flags_errors(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        db_path = str(tmp / "s.sqlite")
        self.assertEqual(quiet_main(["validate", "--db", db_path]), 2)           # no database yet
        self.assertEqual(quiet_main(["init", "--db", db_path]), 0)
        self.assertEqual(quiet_main(["import", "--db", db_path]), 0)
        self.assertEqual(quiet_main(["demo", "--db", db_path]), 0)
        self.assertEqual(quiet_main(["validate", "--db", db_path]), 0)           # real data: warnings only, no errors
        self.assertEqual(quiet_main(["import", "--db", db_path]), 2)             # second import refused
        conn = db.connect(db_path)
        conn.execute("UPDATE configuration SET face_sheet_thickness_mm = -1 WHERE config_code = 'T120'")
        conn.commit()
        conn.close()
        self.assertEqual(quiet_main(["validate", "--db", db_path]), 1)           # deliberate error -> exit status 1
        self.assertEqual(quiet_main(["report", "--db", db_path, "--out", str(tmp / "rep")]), 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["query", str(ROOT / "sql" / "07_cross_solver_comparison.sql"), "--db", db_path]), 0)
            self.assertEqual(cli.main(["query", str(ROOT / "sql" / "01_compare_thickness_configs.sql"), "--db", db_path]), 0)
        self.assertIn("_no rows_", out.getvalue())          # one solver -> empty cross-solver comparison
        self.assertIn("| T160 | 1.6 |", out.getvalue())


class RejectedInputTests(unittest.TestCase):
    """A corrupt structured input is rejected whole; the importer never repairs it and commits nothing."""

    def make_root(self, mutate):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("Report", "Simulation Files (ANSYS)", "Simulation Images"):
            (tmp / name).symlink_to(ROOT / name, target_is_directory=True)
        shutil.copy(ROOT / "README.md", tmp / "README.md")
        (tmp / "data").mkdir()
        with open(ROOT / "data" / "report_values.csv", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        rows = mutate(rows)
        with open(tmp / "data" / "report_values.csv", "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        return tmp

    def import_codes(self, root):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        conn = db.init_db(tmp / "r.sqlite")
        with self.assertRaises(ingest.ImportRejected) as ctx:
            ingest.import_all(conn, root)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_file").fetchone()[0], 0)  # nothing committed
        conn.close()
        return {i.check_code for i in ctx.exception.issues}

    def test_duplicate_and_bad_number_rows_are_rejected(self):
        def mutate(rows):
            rows.append(rows[1])                      # duplicate record
            rows[2][3] = "not-a-number"               # bad numeric value
            rows.append(["result", "0.85"])           # malformed (too few fields)
            return rows
        self.assertTrue({"CSV_DUPLICATE_KEY", "CSV_BAD_NUMBER", "CSV_MALFORMED_ROW"} <= self.import_codes(self.make_root(mutate)))

    def test_unknown_quantity_unit_and_configuration_are_rejected(self):
        def mutate(rows):
            rows[1][2] = "frobnication"
            return rows
        self.assertIn("CSV_UNKNOWN_QUANTITY", self.import_codes(self.make_root(mutate)))

        def mutate_unit(rows):
            rows[1][5] = "furlong"
            return rows
        self.assertIn("CSV_UNKNOWN_UNIT", self.import_codes(self.make_root(mutate_unit)))

        def mutate_config(rows):
            rows[1][1] = "9.99"
            return rows
        self.assertIn("REPORT_ROW_WITHOUT_CONFIG", self.import_codes(self.make_root(mutate_config)))


if __name__ == "__main__":
    unittest.main()
