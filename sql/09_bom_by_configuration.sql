-- query: bom_by_configuration
-- title: Indented BOM per configuration (DEMONSTRATION data)
-- purpose: BOM structure and component relationships with quantities rolled up per assembly
-- demonstration columns: all (part numbers and BOM are illustrative; the structure mirrors the three bodies of the ANSYS model)
-- derived columns: quantity_per_assembly = product of quantities down the tree
WITH RECURSIVE roots AS (
    SELECT DISTINCT b.config_id, b.parent_part_id AS part_id FROM bom_line b
    WHERE NOT EXISTS (SELECT 1 FROM bom_line x WHERE x.config_id = b.config_id AND x.child_part_id = b.parent_part_id)
),
tree(config_id, part_id, level, qty_total, path) AS (
    SELECT r.config_id, r.part_id, 0, 1.0, p.part_number FROM roots r JOIN part p USING (part_id)
    UNION ALL
    SELECT t.config_id, b.child_part_id, t.level + 1, t.qty_total * b.quantity, t.path || ' > ' || c.part_number
    FROM tree t JOIN bom_line b ON b.config_id = t.config_id AND b.parent_part_id = t.part_id JOIN part c ON c.part_id = b.child_part_id
    WHERE t.level < 20
)
SELECT f.config_code, substr('        ', 1, t.level * 2) || p.part_number AS part_number, p.name, p.part_type,
       t.qty_total AS quantity_per_assembly, m.name AS material, p.thickness_mm, p.basis
FROM tree t JOIN configuration f USING (config_id) JOIN part p USING (part_id) LEFT JOIN material m USING (material_id)
ORDER BY f.config_code, t.path;
