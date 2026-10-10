-- query: change_requests
-- title: Engineering change requests, affected items and linked verification results (DEMONSTRATION data)
-- purpose: each change request with its reason, status, affected/proposed parts and configurations, and the verification
--   simulation cases with their documented results
-- source columns: deformation_mm, stress_mpa (documented results of the verification cases)
-- demonstration columns: ecr_code, status, reason, role, item (the change request is simulated; nothing was approved by anyone)
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
SELECT e.ecr_code, e.status, e.basis, e.title, i.role,
       CASE WHEN i.part_id IS NOT NULL THEN 'part' WHEN i.config_id IS NOT NULL THEN 'configuration' ELSE 'simulation_case' END AS item_type,
       COALESCE(pt.part_number, cf.config_code, sc.case_code) AS item, i.note,
       pv.deformation_mm, pv.stress_mpa
FROM change_request e
JOIN ecr_item i ON i.ecr_id = e.ecr_id
LEFT JOIN part pt ON pt.part_id = i.part_id
LEFT JOIN configuration cf ON cf.config_id = i.config_id
LEFT JOIN simulation_case sc ON sc.case_id = i.case_id
LEFT JOIN p AS pv ON pv.case_id = i.case_id
ORDER BY e.ecr_code, CASE i.role WHEN 'affected' THEN 0 WHEN 'proposed' THEN 1 ELSE 2 END, item_type, item;
