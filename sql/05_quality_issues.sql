-- query: quality_issues
-- title: Data-quality issues (latest validation run)
-- purpose: the issues found by `python -m plm validate`, errors first
-- source columns: all (each row is one finding with the affected record and a suggested correction)
-- derived columns: none
SELECT i.severity, i.check_code, i.record_id AS affected_record, i.message AS issue, i.suggested_correction
FROM validation_issue i
WHERE i.run_id = (SELECT MAX(run_id) FROM validation_run)
ORDER BY CASE i.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, i.check_code, i.record_id;
