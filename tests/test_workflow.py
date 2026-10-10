"""BOM, revision and change-request workflows (all DEMONSTRATION data)."""
import shutil
import tempfile
import unittest
from pathlib import Path

from plm import checks, db, ingest, workflow
from .support import ROOT, fresh_db


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db(self)

    def test_seed_is_labelled_as_demonstration_everywhere(self):
        for table in ("part", "change_request", "design_revision"):
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE basis <> 'demonstration'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM part WHERE part_number NOT LIKE 'DEMO-%'").fetchone()[0], 0)

    def test_bom_relationships_and_quantities(self):
        rows = self.conn.execute("""SELECT f.config_code, pp.part_number parent, cp.part_number child, b.quantity
                                    FROM bom_line b JOIN configuration f USING (config_id)
                                    JOIN part pp ON pp.part_id = b.parent_part_id JOIN part cp ON cp.part_id = b.child_part_id
                                    ORDER BY f.config_code, cp.part_number""").fetchall()
        self.assertEqual(len(rows), 6)  # core + face sheets under the assembly, for each of 3 configurations
        self.assertTrue(all(r["parent"] == "DEMO-HSP-1000" for r in rows))
        self.assertEqual({(r["config_code"], r["child"]): r["quantity"] for r in rows}[("T160", "DEMO-HSP-3160")], 2.0)

    def test_bom_matches_configuration_thickness_and_materials(self):
        _run, issues = checks.run_checks(self.conn, ROOT)
        bad = {i.check_code for i in issues} & {"BOM_THICKNESS_MISMATCH", "BOM_MATERIAL_MISMATCH", "BOM_CYCLE", "ECR_STATUS_HISTORY", "ECR_NO_VERIFICATION"}
        self.assertEqual(bad, set())
        self.assertIn("DEMONSTRATION_DATA", {i.check_code for i in issues})

    def test_revision_history_links_configurations_ecr_and_cases(self):
        rows = self.conn.execute("""SELECT r.rev_label, f.config_code, e.ecr_code, s.rev_label sup, c.case_code FROM design_revision r
                                    JOIN configuration f USING (config_id) JOIN simulation_case c ON c.config_id = f.config_id
                                    LEFT JOIN change_request e ON e.ecr_id = r.ecr_id LEFT JOIN design_revision s ON s.rev_id = r.supersedes_rev_id
                                    ORDER BY r.rev_label""").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("A", "T085", None, None, "SIM-T085"), ("B", "T160", "DEMO-ECR-0001", "A", "SIM-T160")])

    def test_ecr_history_is_complete_and_ordered(self):
        steps = self.conn.execute("SELECT from_status, to_status FROM ecr_status_history ORDER BY seq").fetchall()
        self.assertEqual([tuple(r) for r in steps], [(None, "DRAFT"), ("DRAFT", "SUBMITTED"), ("SUBMITTED", "UNDER_REVIEW"),
                                                   ("UNDER_REVIEW", "IMPLEMENTED"), ("IMPLEMENTED", "VERIFIED")])
        self.assertEqual(self.conn.execute("SELECT status FROM change_request").fetchone()[0], "VERIFIED")
        roles = {(r["role"]) for r in self.conn.execute("SELECT role FROM ecr_item")}
        self.assertEqual(roles, {"affected", "proposed", "verification"})


class EcrRuleTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db(self)

    def status(self, code):
        return self.conn.execute("SELECT status FROM change_request WHERE ecr_code = ?", (code,)).fetchone()[0]

    def new_ecr(self, code="DEMO-ECR-0002", items=None):
        workflow.create_ecr(self.conn, code, "test", "reason", items if items is not None else
                            [("affected", "config", "T085", None), ("proposed", "config", "T120", None)])

    def test_illegal_transition_is_rejected_and_nothing_changes(self):
        self.new_ecr()
        with self.assertRaises(workflow.WorkflowError):
            workflow.transition(self.conn, "DEMO-ECR-0002", "VERIFIED")
        self.assertEqual(self.status("DEMO-ECR-0002"), "DRAFT")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ecr_status_history WHERE ecr_id = (SELECT ecr_id FROM change_request WHERE ecr_code = 'DEMO-ECR-0002')").fetchone()[0], 1)

    def test_cannot_submit_without_affected_items(self):
        self.new_ecr(items=[("verification", "case", "SIM-T085", None)])
        with self.assertRaisesRegex(workflow.WorkflowError, "no affected or proposed"):
            workflow.transition(self.conn, "DEMO-ECR-0002", "SUBMITTED")

    def test_cannot_implement_without_a_revision_or_verify_without_results(self):
        self.new_ecr()
        workflow.transition(self.conn, "DEMO-ECR-0002", "SUBMITTED")
        workflow.transition(self.conn, "DEMO-ECR-0002", "UNDER_REVIEW")
        with self.assertRaisesRegex(workflow.WorkflowError, "no design revision"):
            workflow.transition(self.conn, "DEMO-ECR-0002", "IMPLEMENTED")
        workflow.release_revision(self.conn, "HSP", "C", "T120", "DEMO-ECR-0002", "A")
        workflow.transition(self.conn, "DEMO-ECR-0002", "IMPLEMENTED")
        with self.assertRaisesRegex(workflow.WorkflowError, "cannot verify"):          # no verification case linked yet
            workflow.transition(self.conn, "DEMO-ECR-0002", "VERIFIED")
        self.conn.execute("INSERT INTO ecr_item(ecr_id, role, case_id) VALUES ((SELECT ecr_id FROM change_request WHERE ecr_code = 'DEMO-ECR-0002'),"
                          " 'verification', (SELECT case_id FROM simulation_case WHERE case_code = 'SIM-T120'))")
        workflow.transition(self.conn, "DEMO-ECR-0002", "VERIFIED", "evidence linked")
        workflow.transition(self.conn, "DEMO-ECR-0002", "CLOSED")
        self.assertEqual(self.status("DEMO-ECR-0002"), "CLOSED")
        with self.assertRaises(workflow.WorkflowError):                                 # closed is final
            workflow.transition(self.conn, "DEMO-ECR-0002", "DRAFT")

    def test_verification_needs_all_core_results(self):
        self.new_ecr()
        for step in ("SUBMITTED", "UNDER_REVIEW"):
            workflow.transition(self.conn, "DEMO-ECR-0002", step)
        workflow.release_revision(self.conn, "HSP", "C", "T120", "DEMO-ECR-0002")
        workflow.transition(self.conn, "DEMO-ECR-0002", "IMPLEMENTED")
        self.conn.execute("INSERT INTO ecr_item(ecr_id, role, case_id) VALUES ((SELECT ecr_id FROM change_request WHERE ecr_code = 'DEMO-ECR-0002'),"
                          " 'verification', 2)")
        self.conn.execute("DELETE FROM result_metric WHERE case_id = 2 AND metric_name = 'equivalent_stress'")
        with self.assertRaisesRegex(workflow.WorkflowError, "cannot verify"):
            workflow.transition(self.conn, "DEMO-ECR-0002", "VERIFIED")

    def test_revision_rules(self):
        self.new_ecr()
        with self.assertRaisesRegex(workflow.WorkflowError, "not a proposed configuration"):
            workflow.release_revision(self.conn, "HSP", "C", "T085", "DEMO-ECR-0002")   # T085 is only 'affected'
        with self.assertRaises(workflow.WorkflowError):
            workflow.release_revision(self.conn, "HSP", "A", "T085")                     # label already used
        with self.assertRaises(workflow.WorkflowError):
            workflow.release_revision(self.conn, "HSP", "C", "T999")                     # unknown configuration

    def test_unknown_references_are_rejected(self):
        with self.assertRaises(workflow.WorkflowError):
            workflow.create_ecr(self.conn, "DEMO-ECR-0003", "t", "r", [("affected", "part", "NO-SUCH-PART", None)])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM change_request WHERE ecr_code = 'DEMO-ECR-0003'").fetchone()[0], 0)  # rolled back

    def test_status_changed_outside_the_workflow_is_detected(self):
        self.conn.execute("UPDATE change_request SET status = 'CLOSED'")
        self.conn.commit()
        self.assertIn("ECR_STATUS_HISTORY", {i.check_code for i in checks.run_checks(self.conn, ROOT)[1]})

    def test_verified_change_request_without_evidence_is_detected(self):
        self.conn.execute("DELETE FROM ecr_item WHERE role = 'verification'")
        self.conn.commit()
        self.assertIn("ECR_NO_VERIFICATION", {i.check_code for i in checks.run_checks(self.conn, ROOT)[1]})

    def test_bom_integrity_checks(self):
        self.conn.execute("UPDATE part SET thickness_mm = 1.0 WHERE part_number = 'DEMO-HSP-3085'")
        self.conn.execute("INSERT INTO bom_line(config_id, parent_part_id, child_part_id, quantity) VALUES "
                          "((SELECT config_id FROM configuration WHERE config_code = 'T085'), (SELECT part_id FROM part WHERE part_number = 'DEMO-HSP-3085'),"
                          " (SELECT part_id FROM part WHERE part_number = 'DEMO-HSP-1000'), 1)")
        self.conn.commit()
        found = {i.check_code for i in checks.run_checks(self.conn, ROOT)[1]}
        self.assertIn("BOM_THICKNESS_MISMATCH", found)
        self.assertIn("BOM_CYCLE", found)


class BomImportTests(unittest.TestCase):
    HEADER = "config_code,parent_part_number,part_number,part_name,part_type,quantity,find_no,material,thickness_mm\n"

    def load(self, body):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        conn = db.init_db(tmp / "b.sqlite")
        self.addCleanup(conn.close)
        ingest.import_all(conn, ROOT)
        (tmp / "bom.csv").write_text(self.HEADER + body, encoding="utf-8")
        try:
            workflow.import_demo_bom(conn, tmp / "bom.csv")
            return conn, set()
        except ingest.ImportRejected as exc:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM part").fetchone()[0], 0)   # nothing partially loaded
            return conn, {i.check_code for i in exc.issues}

    def test_valid_bom_loads(self):
        conn, codes_ = self.load("T085,,DEMO-A,Assembly,assembly,1,,,\nT085,DEMO-A,DEMO-B,Core,component,1,10,PLA,\n")
        self.assertEqual((codes_, conn.execute("SELECT COUNT(*) FROM bom_line").fetchone()[0]), (set(), 1))

    def test_bad_bom_files_are_rejected_not_repaired(self):
        cases = {
            "duplicate line": ("T085,,DEMO-A,Assembly,assembly,1,,,\nT085,,DEMO-A,Assembly,assembly,1,,,\n", "CSV_DUPLICATE_KEY"),
            "bad quantity": ("T085,,DEMO-A,Assembly,assembly,0,,,\n", "BOM_BAD_QUANTITY"),
            "non-numeric": ("T085,,DEMO-A,Assembly,assembly,two,,,\n", "CSV_BAD_NUMBER"),
            "unknown parent": ("T085,DEMO-X,DEMO-A,Assembly,component,1,,,\n", "BOM_UNKNOWN_PARENT"),
            "unknown material": ("T085,,DEMO-A,Assembly,assembly,1,,Unobtainium,\n", "BOM_UNKNOWN_MATERIAL"),
            "unknown config": ("T999,,DEMO-A,Assembly,assembly,1,,,\n", "BOM_UNKNOWN_CONFIG"),
            "part type": ("T085,,DEMO-A,Assembly,gizmo,1,,,\n", "CSV_BAD_VALUE"),
            "spelling duplicate": ("T085,,DEMO-A,Assembly,assembly,1,,,\nT120,,demo-a,Assembly,assembly,1,,,\n", "DUPLICATE_PART_NUMBER"),
            "conflicting definition": ("T085,,DEMO-A,Assembly,assembly,1,,,\nT120,,DEMO-A,Other name,assembly,1,,,\n", "BOM_CONFLICTING_PART"),
        }
        for name, (body, expected) in cases.items():
            with self.subTest(name):
                self.assertIn(expected, self.load(body)[1])


if __name__ == "__main__":
    unittest.main()
