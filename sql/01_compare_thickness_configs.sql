-- query: compare_thickness_configs
-- title: Deformation, stress and strain by face-sheet thickness
-- purpose: compare the existing face-sheet thickness configurations (0.85 / 1.2 / 1.6 mm) against the thinnest one
-- source columns: deformation_mm, stress_mpa, strain (documented ANSYS results; report Table 6, README as fallback; stress in MPa)
-- derived columns: *_change_pct_vs_baseline = 100 * (value - baseline) / baseline, baseline = thinnest face sheet. Calculated here, not source data.
-- usage: sqlite3 build/honeycomb_plm.sqlite < sql/01_compare_thickness_configs.sql
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
SELECT p.config_code, p.thickness_mm, p.deformation_mm, p.stress_mpa, p.strain,
       ROUND(100.0 * (p.deformation_mm - b.deformation_mm) / b.deformation_mm, 2) AS deformation_change_pct_vs_baseline,
       ROUND(100.0 * (p.stress_mpa     - b.stress_mpa)     / b.stress_mpa,     2) AS stress_change_pct_vs_baseline,
       ROUND(100.0 * (p.strain         - b.strain)         / b.strain,         2) AS strain_change_pct_vs_baseline
FROM p, (SELECT * FROM p ORDER BY thickness_mm LIMIT 1) AS b
ORDER BY p.thickness_mm;
