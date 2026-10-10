-- query: summary_by_solver_material
-- title: Available results by solver and material
-- purpose: summarise what exists, grouped by solver, analysis type, core material and face-sheet material
-- source columns: cases, configurations, metrics_available, metrics_missing, min/max deformation and stress (documented values)
-- derived columns: none (counts and min/max only)
-- note: groups by (solver, core material, face-sheet material); with one solver and one material pair the table has one row.
WITH facts AS (
    SELECT case_id, metric_name, component, value, 'ok' AS status FROM v_result_primary
    UNION ALL
    SELECT case_id, metric_name, component, NULL, status FROM result_metric WHERE status = 'missing'
)
SELECT s.name || ' ' || s.version AS solver, c.analysis_type, mc.name AS core_material, mf.name AS face_sheet_material,
       COUNT(DISTINCT c.case_id)        AS cases,
       COUNT(DISTINCT f.config_id)      AS configurations,
       COUNT(DISTINCT CASE WHEN k.status = 'ok'      THEN k.case_id || ':' || k.metric_name || ':' || k.component END) AS metrics_available,
       COUNT(DISTINCT CASE WHEN k.status = 'missing' THEN k.case_id || ':' || k.metric_name || ':' || k.component END) AS metrics_missing,
       MIN(CASE WHEN k.metric_name = 'total_deformation' THEN k.value END) AS min_deformation_mm,
       MAX(CASE WHEN k.metric_name = 'total_deformation' THEN k.value END) AS max_deformation_mm,
       MIN(CASE WHEN k.metric_name = 'equivalent_stress' THEN k.value END) AS min_stress_mpa,
       MAX(CASE WHEN k.metric_name = 'equivalent_stress' THEN k.value END) AS max_stress_mpa
FROM facts k
JOIN simulation_case c ON c.case_id = k.case_id
JOIN solver s          ON s.solver_id = c.solver_id
JOIN configuration f   ON f.config_id = c.config_id
LEFT JOIN material mc  ON mc.material_id = f.core_material_id
LEFT JOIN material mf  ON mf.material_id = f.face_sheet_material_id
GROUP BY s.name, s.version, c.analysis_type, mc.name, mf.name;
