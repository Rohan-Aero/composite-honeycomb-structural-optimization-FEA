-- query: cross_solver_comparison
-- title: Cross-solver comparison (only genuinely corresponding results)
-- purpose: compare a result across two solvers ONLY where both solvers have a value for the same configuration, analysis type,
--   metric, statistic and component. Anything else is not comparable and is not listed.
-- source columns: value_a, value_b (documented / solver values in the canonical unit)
-- derived columns: difference_pct_b_vs_a
-- note: the current repository has a single solver (ANSYS MAPDL 2025 R1), so this query correctly returns no rows.
SELECT f.config_code, a.metric_name, a.statistic, a.component, a.unit,
       sa.name || ' ' || sa.version AS solver_a, a.value AS value_a,
       sb.name || ' ' || sb.version AS solver_b, b.value AS value_b,
       ROUND(100.0 * (b.value - a.value) / a.value, 3) AS difference_pct_b_vs_a
FROM v_result_primary a
JOIN simulation_case ca ON ca.case_id = a.case_id
JOIN solver sa          ON sa.solver_id = ca.solver_id
JOIN simulation_case cb ON cb.config_id = ca.config_id AND cb.solver_id > ca.solver_id AND cb.analysis_type = ca.analysis_type
JOIN solver sb          ON sb.solver_id = cb.solver_id
JOIN v_result_primary b ON b.case_id = cb.case_id AND b.metric_name = a.metric_name AND b.statistic = a.statistic AND b.component = a.component
JOIN configuration f    ON f.config_id = ca.config_id
ORDER BY f.config_code, a.metric_name;
