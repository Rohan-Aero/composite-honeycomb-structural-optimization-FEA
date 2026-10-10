-- query: rank_configurations
-- title: Ranking of configurations by engineering metric
-- purpose: rank configurations (1 = best) by deformation, stress, strain, mass and a specific-stiffness proxy
-- source columns: deformation_mm, stress_mpa, strain (documented), mass_g (ANSYS mass summary)
-- derived columns: stiffness_n_per_mm = applied force / maximum total deformation; specific_stiffness = stiffness / mass.
--   The force is the load resultant derived from the solver deck (equal load in all cases). This is a proxy: maximum deformation is
--   not the deflection at the load point, so treat the numbers as indicative. Ranks use RANK(): ties share a rank.
-- note: different metrics give different winners; no single "optimal" configuration follows from this table alone.
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
),
f AS (SELECT case_id, value_num AS force_n FROM simulation_input WHERE param_name = 'applied_force' AND origin = 'derived')
SELECT p.config_code, p.thickness_mm, p.deformation_mm, p.stress_mpa, p.strain, p.mass_g,
       ROUND(f.force_n / p.deformation_mm, 0)              AS stiffness_n_per_mm,
       ROUND(f.force_n / p.deformation_mm / p.mass_g, 2)   AS specific_stiffness_n_per_mm_per_g,
       RANK() OVER (ORDER BY p.deformation_mm)                          AS rank_lowest_deformation,
       RANK() OVER (ORDER BY p.stress_mpa)                              AS rank_lowest_stress,
       RANK() OVER (ORDER BY p.strain)                                  AS rank_lowest_strain,
       RANK() OVER (ORDER BY p.mass_g)                                  AS rank_lightest,
       RANK() OVER (ORDER BY f.force_n / p.deformation_mm / p.mass_g DESC) AS rank_highest_specific_stiffness
FROM p JOIN f USING (case_id)
ORDER BY rank_lowest_deformation;
