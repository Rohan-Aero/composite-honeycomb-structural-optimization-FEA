-- query: change_request_history
-- title: Change-request status history (DEMONSTRATION data)
-- purpose: ordered status transitions of each change request (timestamps are in ecr_status_history.changed_utc)
-- demonstration columns: all
SELECT e.ecr_code, h.seq, COALESCE(h.from_status, '(created)') AS from_status, h.to_status, h.note
FROM ecr_status_history h JOIN change_request e USING (ecr_id)
ORDER BY e.ecr_code, h.seq;
