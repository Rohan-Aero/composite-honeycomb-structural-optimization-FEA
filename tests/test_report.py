import csv
import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path

from plm import checks, report
from .support import ROOT, fresh_db


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, out):
        conn = fresh_db(self)
        checks.run_checks(conn, ROOT)
        return report.generate(conn, out, ROOT / "sql")

    def test_reports_charts_and_csv_are_written(self):
        counts = self.build(self.out / "a")
        self.assertEqual(counts["error"], 0)
        a = self.out / "a"
        for name in ("engineering_report.md", "data_quality_report.md", "data_quality_report.csv", "query_outputs/01_compare_thickness_configs.csv",
                     "query_outputs/08_traceability.csv", "charts/total_deformation_by_thickness.svg"):
            self.assertTrue((a / name).is_file(), name)
        for svg in (a / "charts").glob("*.svg"):
            xml.dom.minidom.parse(str(svg))                                              # well-formed XML

    def test_data_quality_report_has_severity_record_and_suggested_correction(self):
        self.build(self.out / "b")
        with open(self.out / "b" / "data_quality_report.csv", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0]), ["severity", "check_code", "table", "affected_record", "issue", "suggested_correction", "source_file"])
        self.assertTrue(all(r["severity"] in ("error", "warning", "info") and r["suggested_correction"] and r["issue"] for r in rows))
        md = (self.out / "b" / "data_quality_report.md").read_text(encoding="utf-8")
        for needle in ("Checks executed", "Suggested correction", "DUPLICATE_SOURCE_CONTENT", "does **not** show that the FEA results are physically valid"):
            self.assertIn(needle, md)

    def test_engineering_report_separates_source_derived_and_demonstration(self):
        self.build(self.out / "c")
        md = (self.out / "c" / "engineering_report.md").read_text(encoding="utf-8")
        for needle in ("**SOURCE**", "**DERIVED**", "**DEMONSTRATION**", "DEMONSTRATION data: BOM, revisions and change request",
                       "no cross-solver comparison is possible", "-20.72", "Traceability example"):
            self.assertIn(needle, md)

    def test_report_generation_is_deterministic_and_does_not_change_the_database(self):
        conn = fresh_db(self)
        checks.run_checks(conn, ROOT)
        before = conn.execute("SELECT COUNT(*), SUM(value) FROM result_metric").fetchone()[:]
        report.generate(conn, self.out / "d1", ROOT / "sql")
        report.generate(conn, self.out / "d2", ROOT / "sql")
        for f in ("engineering_report.md", "data_quality_report.md", "charts/specific_stiffness_by_thickness.svg"):
            self.assertEqual((self.out / "d1" / f).read_bytes(), (self.out / "d2" / f).read_bytes(), f)
        self.assertEqual(conn.execute("SELECT COUNT(*), SUM(value) FROM result_metric").fetchone()[:], before)

    def test_report_requires_a_validation_run(self):
        conn = fresh_db(self)
        with self.assertRaises(RuntimeError):
            report.generate(conn, self.out / "e", ROOT / "sql")


if __name__ == "__main__":
    unittest.main()
