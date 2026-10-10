-- query: missing_data
-- title: Missing data
-- purpose: list every expected result that is not available, and configurations without a simulation case
-- source columns: availability, value, unit (documented / solver values), reason (as recorded by the importer)
-- derived columns: none
WITH expected(metric_name) AS (
    VALUES ('total_deformation'), ('equivalent_stress'), ('equivalent_elastic_strain'),
           ('directional_deformation'), ('strain_energy'), ('volume')
)
SELECT c.case_code AS record, e.metric_name AS item,
       CASE WHEN p.result_id IS NOT NULL THEN 'available' ELSE 'MISSING' END AS availability,
       p.value, COALESCE(p.unit, q.canonical_unit) AS unit, m.missing_reason AS reason
FROM simulation_case c
CROSS JOIN expected e
JOIN quantity_def q ON q.quantity = e.metric_name
LEFT JOIN v_result_primary p ON p.case_id = c.case_id AND p.metric_name = e.metric_name AND p.component = 'assembly'
LEFT JOIN result_metric m ON m.case_id = c.case_id AND m.metric_name = e.metric_name AND m.status = 'missing'
UNION ALL
SELECT f.config_code, '(simulation case)', 'MISSING', NULL, NULL, 'configuration has no simulation case'
FROM configuration f WHERE f.config_id NOT IN (SELECT config_id FROM simulation_case)
ORDER BY availability DESC, record, item;
