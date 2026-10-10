"""Data-quality checks must pass real data, report its genuine inconsistencies, and catch deliberately injected errors."""
import io
import unittest

from plm import checks
from .support import ROOT, fresh_db


def codes(issues, severity=None):
    return {i.check_code for i in issues if severity is None or i.severity == severity}


class RealDataTests(unittest.TestCase):
    def test_real_data_has_no_errors_and_the_known_warnings(self):
        conn = fresh_db(self)
        _run, issues = checks.run_checks(conn, ROOT)
        self.assertEqual(codes(issues, "error"), set())
        self.assertEqual(codes(issues, "warning"), {"DUPLICATE_SOURCE_CONTENT", "MATERIAL_DOC_VS_DECK", "MATERIAL_LABEL_MISMATCH",
                                                    "README_CLAIM", "UNIT_LABEL_MISMATCH"})
        dup = next(i for i in issues if i.check_code == "DUPLICATE_SOURCE_CONTENT")
        self.assertIn("0.85mm/Main file/WORKBENCH N MECH.wbpj", dup.message + str(dup.record_id))
        self.assertIn("T085,T160", dup.message)
        self.assertEqual(sum(i.check_code == "RESULT_OPTIONAL_MISSING" for i in issues), 9)
        self.assertTrue(all(i.suggested_correction for i in issues))        # every finding says how to fix it

    def test_checks_that_prove_consistency_pass_on_real_data(self):
        conn = fresh_db(self)
        _run, issues = checks.run_checks(conn, ROOT)
        for passed in ("README_REPORT_ROUNDING", "SOLVER_VS_DOCUMENTED_DEFORMATION", "FACE_THICKNESS_MASS_MISMATCH", "CORE_MASS_CONSTANT",
                       "LOAD_VS_DOCUMENTED", "NOT_COMPARABLE", "REPORT_TRANSCRIPTION", "SOURCE_FILE_CHANGED"):
            self.assertNotIn(passed, codes(issues))

    def test_run_is_stored_and_does_not_touch_source_values(self):
        conn = fresh_db(self)
        before = conn.execute("SELECT SUM(value), COUNT(*) FROM result_metric").fetchone()[:]
        run, issues = checks.run_checks(conn, ROOT)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM validation_issue WHERE run_id = ?", (run,)).fetchone()[0], len(issues))
        self.assertEqual(conn.execute("SELECT SUM(value), COUNT(*) FROM result_metric").fetchone()[:], before)


class InjectedErrorTests(unittest.TestCase):
    """Each test corrupts a private copy of the database and expects a specific check to notice."""

    def setUp(self):
        self.conn = fresh_db(self)

    def run_checks(self, *sql, fk_off=False):
        if fk_off:
            self.conn.execute("PRAGMA foreign_keys = OFF")
        for s in sql:
            self.conn.execute(s)
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")
        issues = checks.run_checks(self.conn, ROOT)[1]
        self.assertNotIn("CHECK_ABORTED", codes(issues))  # corrupt data must be reported, not crash a check
        return issues

    def assertDetected(self, issues, code, severity):
        self.assertIn((code, severity), {(i.check_code, i.severity) for i in issues}, f"{code} not reported")

    def test_missing_required_value(self):
        self.assertDetected(self.run_checks("UPDATE configuration SET face_sheet_thickness_mm = NULL WHERE config_code = 'T120'"),
                            "REQUIRED_VALUE_MISSING", "error")

    def test_result_marked_ok_without_value_and_status_inconsistency(self):
        issues = self.run_checks("UPDATE result_metric SET value = NULL WHERE result_id = 1",
                                 "UPDATE result_metric SET value = 1.0 WHERE status = 'missing' AND result_id = (SELECT MIN(result_id) FROM result_metric WHERE status = 'missing')")
        self.assertDetected(issues, "REQUIRED_VALUE_MISSING", "error")
        self.assertDetected(issues, "STATUS_INCONSISTENT", "error")

    def test_invalid_geometry_material_and_load_parameters(self):
        issues = self.run_checks("UPDATE configuration SET face_sheet_thickness_mm = -0.85 WHERE config_code = 'T085'",
                                 "UPDATE material_property SET value = -3500 WHERE quantity = 'youngs_modulus' AND property_id = (SELECT MIN(property_id) FROM material_property WHERE quantity = 'youngs_modulus')",
                                 "UPDATE material_property SET value = 0.7 WHERE quantity = 'poissons_ratio' AND property_id = (SELECT MIN(property_id) FROM material_property WHERE quantity = 'poissons_ratio')",
                                 "UPDATE simulation_input SET value_num = 0 WHERE param_name = 'applied_pressure' AND case_id = 2")
        self.assertDetected(issues, "INVALID_GEOMETRY", "error")
        self.assertEqual(sum(i.check_code == "INVALID_MATERIAL_PARAMETER" for i in issues), 2)
        self.assertDetected(issues, "INVALID_LOAD", "error")

    def test_negative_magnitude_and_absurd_strain(self):
        issues = self.run_checks("UPDATE result_metric SET value = -2.9 WHERE metric_name = 'equivalent_stress' AND case_id = 1",
                                 "UPDATE result_metric SET value = 3.0 WHERE metric_name = 'equivalent_elastic_strain' AND case_id = 2")
        self.assertDetected(issues, "INVALID_RESULT_VALUE", "error")
        self.assertDetected(issues, "INVALID_RESULT_VALUE", "warning")

    def test_text_in_numeric_column(self):
        self.assertDetected(self.run_checks("UPDATE result_metric SET value = 'n/a' WHERE metric_name = 'total_deformation' AND case_id = 1"),
                            "TYPE_MISMATCH", "error")

    def test_duplicate_part_numbers_hidden_by_spelling(self):
        issues = self.run_checks("INSERT INTO part(part_number, name, part_type) VALUES ('DEMOHSP2000', 'duplicate core', 'component')")
        self.assertDetected(issues, "DUPLICATE_PART_NUMBER", "error")

    def test_duplicate_configuration_thickness(self):
        issues = self.run_checks("INSERT INTO configuration(product_id, config_code, face_sheet_thickness_mm) VALUES (1, 'T120B', 1.2)")
        self.assertDetected(issues, "DUPLICATE_CONFIGURATION", "error")
        self.assertDetected(issues, "CONFIG_WITHOUT_CASE", "error")

    def test_inconsistent_units_and_formats(self):
        issues = self.run_checks("UPDATE result_metric SET unit = 'Pa' WHERE metric_name = 'equivalent_stress' AND case_id = 1",
                                 "UPDATE result_metric SET original_unit = 'kg' WHERE metric_name = 'total_deformation' AND case_id = 2 AND original_unit = 'mm'",
                                 "UPDATE result_metric SET original_unit = 'furlong' WHERE metric_name = 'total_mass' AND case_id = 3")
        self.assertDetected(issues, "UNIT_NOT_CANONICAL", "error")
        self.assertDetected(issues, "UNIT_LABEL_MISMATCH", "warning")
        self.assertDetected(issues, "UNKNOWN_UNIT", "error")

    def test_missing_links_between_configuration_case_and_results(self):
        issues = self.run_checks("DELETE FROM result_metric WHERE case_id = 2 AND metric_name = 'equivalent_stress'",
                                 "DELETE FROM artifact_link WHERE case_id = 3 AND role = 'solver_input_deck'")
        self.assertDetected(issues, "CASE_WITHOUT_CORE_RESULT", "error")
        self.assertDetected(issues, "CASE_MISSING_ARTIFACT", "warning")

    def test_orphan_rows_violate_foreign_keys(self):
        issues = self.run_checks("DELETE FROM simulation_case WHERE case_id = 3", fk_off=True)
        self.assertDetected(issues, "FK_VIOLATION", "error")

    def test_case_without_load_or_boundary_condition(self):
        issues = self.run_checks("DELETE FROM simulation_input WHERE case_id = 1 AND param_name IN ('applied_pressure', 'applied_force', 'fixed_support')")
        self.assertDetected(issues, "CASE_NO_LOAD", "error")
        self.assertDetected(issues, "CASE_NO_BOUNDARY_CONDITION", "error")

    def test_cases_that_differ_in_more_than_thickness_are_not_comparable(self):
        issues = self.run_checks("UPDATE simulation_input SET value_num = value_num * 1.1 WHERE param_name = 'applied_pressure' AND case_id = 3",
                                 "UPDATE simulation_input SET value_num = 20000 WHERE param_name = 'node_count' AND case_id = 2",
                                 "UPDATE material_property SET value = 8000 WHERE quantity = 'youngs_modulus' AND case_id = 2 AND value = 9000")
        nc = [i for i in issues if i.check_code == "NOT_COMPARABLE"]
        text = " ".join(i.message for i in nc)
        self.assertIn("applied_pressure", text)
        self.assertIn("node_count", text)
        self.assertIn("youngs_modulus", text)
        self.assertDetected(issues, "MATERIAL_CARD_INCONSISTENT", "warning")

    def test_different_solver_makes_cases_not_comparable(self):
        issues = self.run_checks("INSERT INTO solver(name, version) VALUES ('OtherSolver', '1.0')",
                                 "UPDATE simulation_case SET solver_id = (SELECT MAX(solver_id) FROM solver) WHERE case_id = 2")
        self.assertIn("solver", " ".join(i.message for i in issues if i.check_code == "NOT_COMPARABLE"))

    def test_readme_and_report_disagree_beyond_rounding(self):
        issues = self.run_checks("UPDATE result_metric SET value = 0.0080, original_value = 0.0080 WHERE case_id = 1 AND metric_name = 'total_deformation'"
                                 " AND source_file_id = (SELECT source_file_id FROM source_file WHERE file_kind = 'readme')")
        self.assertDetected(issues, "README_REPORT_ROUNDING", "error")

    def test_solver_monitor_contradicts_documented_deformation(self):
        issues = self.run_checks("UPDATE result_metric SET value = 0.001 WHERE case_id = 1 AND metric_name = 'total_deformation'"
                                 " AND source_file_id = (SELECT source_file_id FROM source_file WHERE file_kind = 'report_pdf')")
        self.assertDetected(issues, "SOLVER_VS_DOCUMENTED_DEFORMATION", "error")

    def test_mislabelled_configuration_is_caught_by_mass_check(self):
        issues = self.run_checks("UPDATE configuration SET face_sheet_thickness_mm = 2.0 WHERE config_code = 'T120'")
        self.assertDetected(issues, "FACE_THICKNESS_MASS_MISMATCH", "warning")

    def test_documented_load_that_does_not_match_the_deck(self):
        issues = self.run_checks("UPDATE simulation_input SET value_num = 900 WHERE param_name = 'applied_force' AND origin = 'documented'")
        self.assertDetected(issues, "LOAD_VS_DOCUMENTED", "warning")

    def test_source_file_changed_after_import(self):
        issues = self.run_checks("UPDATE source_file SET sha256 = '0000' WHERE rel_path = 'README.md'")
        self.assertDetected(issues, "SOURCE_FILE_CHANGED", "error")

    def test_identical_files_in_different_configurations(self):
        same = "SELECT sha256 FROM source_file WHERE archive_member LIKE '%/MECH/solve.out' ORDER BY source_file_id LIMIT 1"
        issues = self.run_checks(f"UPDATE source_file SET sha256 = ({same}) WHERE archive_member LIKE '%/MECH/solve.out'")
        self.assertTrue(any(i.check_code == "DUPLICATE_SOURCE_CONTENT" and "solve.out" in str(i.record_id) for i in issues))

    def test_readme_claims_are_recomputed_from_the_data(self):
        text = "Achieved ~50% reduction in total deformation. Improved stiffness-to-weight ratio significantly"
        issues = checks._readme_claims(text, list(checks._case_table(self.conn).values()))
        self.assertEqual([i.check_code for i in issues], ["README_CLAIM", "README_CLAIM"])
        self.assertIn("20.7", issues[0].message)

    def test_transcription_check_detects_a_wrong_number(self):
        import shutil
        import tempfile
        from pathlib import Path
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext not installed")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "data").mkdir()
        (tmp / "Report").symlink_to(ROOT / "Report", target_is_directory=True)
        text = (ROOT / "data" / "report_values.csv").read_text(encoding="utf-8").replace("0.0070107,0.0070107", "0.0070107,0.0071007", 1)
        (tmp / "data" / "report_values.csv").write_text(text, encoding="utf-8")
        found = checks.check_report_transcription(self.conn, tmp)
        self.assertEqual([i.check_code for i in found], ["REPORT_TRANSCRIPTION"])


class CsvRowCheckTests(unittest.TestCase):
    def rows(self, text):
        import csv
        reader = csv.DictReader(io.StringIO(text))
        return [(reader.line_num, r) for r in reader]

    def test_row_level_problems(self):
        text = "id,qty,kind\nA,1,x\nA,2,x\nB,,x\nC,abc,x\nD,3,bad\nE,4\n"
        issues = checks.check_csv_rows(self.rows(text), "t.csv", required=("id", "qty"), numeric=("qty",), enums={"kind": {"x"}}, key=("id",))
        self.assertEqual(sorted(codes(issues)), ["CSV_BAD_NUMBER", "CSV_BAD_VALUE", "CSV_DUPLICATE_KEY", "CSV_MALFORMED_ROW", "CSV_MISSING_VALUE"])
        self.assertTrue(all(i.severity == "error" for i in issues))

    def test_clean_rows_pass(self):
        self.assertEqual(checks.check_csv_rows(self.rows("id,qty\nA,1\nB,2\n"), "t.csv", required=("id",), numeric=("qty",), key=("id",)), [])


if __name__ == "__main__":
    unittest.main()
