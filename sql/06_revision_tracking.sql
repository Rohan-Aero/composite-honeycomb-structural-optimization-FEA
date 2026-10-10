-- query: revision_tracking
-- title: Design revisions and their linked simulation cases (DEMONSTRATION data)
-- purpose: follow each design revision to its configuration, change request, simulation case and results
-- source columns: config_code, thickness_mm, case_code, project_saved_utc, deformation_mm, stress_mpa (documented results)
-- demonstration columns: rev_label, supersedes, ecr_code, ecr_status, basis (revisions and the ECR are illustrative, not real records)
-- derived columns: none
WITH p AS (
    SELECT c.case_id, c.case_code, f.config_code, f.face_sheet_thickness_mm AS thickness_mm,
           MAX(CASE WHEN r.metric_name = 'total_deformation'         THEN r.value END) AS deformation_mm,
           MAX(CASE WHEN r.metric_name = 'equivalent_stress'         THEN r.value END) AS stress_mpa,
           MAX(CASE WHEN r.metric_name = 'equivalent_elastic_strain' THEN r.value END) AS strain,
           MAX(CASE WHEN r.metric_name = 'total_mass'                THEN r.value END) AS mass_g
    FROM simulation_case c
    JOIN configuration f USING (config_id)
    LEFT JOIN v_result_primary r ON r.case_id = c.case_id AND r.component = 'assembly'
    GROUP BY c.case_id
)
SELECT r.rev_label, r.basis, sup.rev_label AS supersedes, p.config_code, p.thickness_mm, e.ecr_code, e.status AS ecr_status,
       p.case_code, c.project_saved_utc, p.deformation_mm, p.stress_mpa
FROM design_revision r
JOIN p ON p.config_code = (SELECT config_code FROM configuration WHERE config_id = r.config_id)
JOIN simulation_case c ON c.case_id = p.case_id
LEFT JOIN design_revision sup ON sup.rev_id = r.supersedes_rev_id
LEFT JOIN change_request e ON e.ecr_id = r.ecr_id
ORDER BY r.rev_id;
