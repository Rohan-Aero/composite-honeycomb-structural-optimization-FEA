-- query: traceability
-- title: Traceability from configuration to inputs, outputs and source files
-- purpose: for every configuration/case list each input, result and material property with its origin, source file,
--   archive member, line/table locator and the SHA-256 of the source file (or member)
-- source columns: value, unit, source_file, archive_member, locator, sha256
-- derived rows: origin = 'derived' marks values calculated from source values (see simulation_input.derivation)
-- usage: add  WHERE config_code = 'T085'  to trace one configuration
SELECT * FROM (
    SELECT f.config_code, c.case_code, 'input' AS kind, i.param_name AS item, COALESCE(i.value_num, i.value_text) AS value, i.unit,
           i.origin, sf.rel_path AS source_file, sf.archive_member, i.locator, sf.sha256
    FROM simulation_input i JOIN simulation_case c USING (case_id) JOIN configuration f USING (config_id) JOIN source_file sf USING (source_file_id)
    UNION ALL
    SELECT f.config_code, c.case_code, 'result', r.metric_name || ' [' || r.component || ']',
           COALESCE(r.value, 'MISSING'), r.unit, r.origin, sf.rel_path, sf.archive_member, r.locator, sf.sha256
    FROM result_metric r JOIN simulation_case c USING (case_id) JOIN configuration f USING (config_id) JOIN source_file sf USING (source_file_id)
    UNION ALL
    SELECT f.config_code, c.case_code, 'material_property', m.name || ' ' || p.quantity, p.value, p.unit, p.origin,
           sf.rel_path, sf.archive_member, p.locator, sf.sha256
    FROM material_property p JOIN material m USING (material_id) JOIN source_file sf USING (source_file_id)
    JOIN simulation_case c ON c.case_id = p.case_id JOIN configuration f USING (config_id)
)
ORDER BY config_code, kind, item, origin;
