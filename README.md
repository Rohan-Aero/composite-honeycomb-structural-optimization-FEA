# Composite Honeycomb Sandwich Panel Optimization (FEA)

## Objective
To investigate and optimize the structural performance of composite honeycomb sandwich panels for lightweight aerospace applications using Finite Element Analysis (FEA).

---

## Tools & Software
- ANSYS Workbench
- ANSYS Mechanical
- ANSYS SpaceClaim

---

## Methodology
- Designed hexagonal honeycomb core geometry in ANSYS SpaceClaim  
- Performed static structural analysis in ANSYS Mechanical  
- Conducted parametric study on face sheet thickness (0.85 mm – 1.6 mm)  
- Evaluated deformation, stress distribution, and stiffness characteristics  

---

## Material Configuration

All three cases use the same materials:
- **Core Material:** PLA (Polylactic Acid)
- **Face Sheet Material:** ePA-CF (Carbon Fiber Reinforced)

Only face sheet thickness varies:
| Case | Face Sheet Thickness |
|------|---------------------|
| 1    | 0.85 mm             |
| 2    | 1.2 mm              |
| 3    | 1.6 mm              |

---

## Model Setup

- *Core Material:* PLA  
- *Face Sheets:* Carbon Fiber Reinforced  
- *Boundary Conditions:* Bottom face fully fixed; 1000 N applied as uniform pressure (≈0.144 MPa) over the top face, i.e. a flatwise compression setup  
- *Mesh Strategy:* Quad-dominant solid mesh (SOLID186), 2,093 solid elements / 14,009 nodes, identical for all three cases; no convergence study yet  

---

## Results
- ~21% reduction in **peak** total deformation from 0.85 mm to 1.6 mm (the peak occurs at the unsupported overhanging edge of the top face sheet); average deformation drops only ~2%  
- *1.6 mm* gave the lowest deformation and stress of the three cases tested, at ~29% more mass than 0.85 mm  
- Stiffness-to-weight ratio did not improve significantly: based on peak deformation, 1.2 mm is ~3% better than 0.85 mm and 1.6 mm is ~2% worse  

---

## Detailed Results

| Thickness | Max Deformation (mm) | Avg Deformation (mm) | Von Mises Stress (MPa) | Elastic Strain | Mass (g) |
|-----------|----------------------|----------------------|------------------------|----------------|----------|
| 0.85 mm   | 0.00701              | 0.00214              | 2.9896                 | 0.000896       | 41.0     |
| 1.2 mm    | 0.00601              | 0.00211              | 2.9189                 | 0.000876       | 46.6     |
| 1.6 mm    | 0.00556              | 0.00210              | 2.8536                 | 0.000857       | 53.0     |

**~21% reduction in peak deformation from 0.85mm to 1.6mm (~2% in average deformation)**

---

## Key Insights
- Structural stiffness increases with face sheet thickness  
- Honeycomb geometry provides high strength with low weight  
- Optimization is critical for aerospace structural efficiency  

---

## Future Improvements
- Mesh convergence study  
- Buckling analysis  
- Dynamic loading conditions


---

# Extension: PLM-inspired engineering data management

A small engineering-data system built **around** the FEA study above (nothing above this line, and none of the CAD, ANSYS, image or report
files, was changed). It loads the study into a relational SQLite database, keeps every value traceable to its source file, checks the data
quality, and answers questions about the three face-sheet configurations with documented SQL.

> **What is real and what is not.** Simulation inputs, solver outputs and the documented results come from the repository files.
> The BOM, part numbers (`DEMO-...`), design revisions and the engineering change request are a **demonstration** workflow created by
> `python -m plm demo`. They are not records of a real PLM system and nothing was approved by any organisation. Derived values (percent
> changes, stiffness proxy) are calculated by queries and labelled as such; nothing is invented, and values that are not available
> are stored as *missing*.

## Quick start

Requirements: Python 3.9+ with its standard library only (SQLite 3.25+ for window functions; every current Python bundles it).
Optional: `pdftotext` (poppler) enables a check that each transcribed report value really appears on the cited PDF page.
No other dependency, no absolute paths: everything is resolved relative to the repository.

```bash
python -m plm all                    # init (rebuild) -> import -> demo -> validate -> report
python -m unittest discover -v       # 78 automated tests
```

or step by step (`--db FILE` and `--root DIR` are accepted by every command):

```bash
python -m plm init [--force]         # create build/honeycomb_plm.sqlite from plm/schema.sql
python -m plm import                 # ANSYS archives + README + report values -> database (sources are read-only)
python -m plm demo                   # DEMONSTRATION BOM, revisions A/B, change request DEMO-ECR-0001
python -m plm validate               # data-quality checks; exit status 1 if any *error*
python -m plm report [--out DIR]     # generated_reports/: Markdown, CSV, SVG charts
python -m plm query sql/01_compare_thickness_configs.sql    # run any SQL file and print the table
```

`init` never overwrites an existing database without `--force` (the database is a derived artifact and is git-ignored). `import` refuses
to run twice and rejects a malformed input file as a whole instead of repairing it.

## What is imported, and from where

| Data | Source file | Notes |
|---|---|---|
| Configurations 0.85 / 1.2 / 1.6 mm | `Simulation Files (ANSYS)/<t>mm/` | thickness also confirmed from solver mass (below) |
| Solver, run time, mesh, mass, warnings | `solve.out` in each `.wbpz` | ANSYS MAPDL 2025 R1, build 25.1 |
| Materials, load, fixed support | `ds.dat` + `MatML.xml` in each `.wbpz` | PLA core, ePA-CF face sheets; load = pressure x computed area |
| Max displacement component | `file.mntr` | cross-check on the documented deformation |
| Deformation, stress, strain | README table and report Table 6 | report values are page-referenced in `data/report_values.csv` |
| Every file (98) | SHA-256 + size, including all members of the `.wbpz` archives | `source_file` table |

Each result, input and material property stores the source file, the archive member, a line/table locator, the **value and unit as
printed**, and the canonical value (e.g. report stress `2989600 Pa` -> `2.9896 MPa`). The raw binary results (`file.rst`, `.mechdb`) are not
parsed, so directional deformation, strain energy and volume (only available as contour images) are recorded as **missing**.

## Schema

21 tables and one view, foreign keys enforced, uniqueness constraints on every natural key, indexes on the main join and provenance columns. Full description with
an ER diagram: [`docs/schema.md`](docs/schema.md).

```
project -> product -> configuration -> simulation_case -> simulation_input / result_metric / material_property
                          |                  |                              \-> source_file (file, member, line, SHA-256)
                          |                  \-> solver
                          +-> bom_line <- part                               (demonstration BOM)
                          +-> design_revision <- change_request -> ecr_item  (demonstration revisions / ECR, linked to cases)
quantity_def (canonical units)   artifact_link (file roles)   validation_run -> validation_issue
```

## Results from the available data

Source values (documented ANSYS results) with derived percent changes versus 0.85 mm (query `sql/01_compare_thickness_configs.sql`):

| Config | Thickness (mm) | Deformation (mm) | Stress (MPa) | Strain | Deformation vs 0.85 mm | Stress vs 0.85 mm |
|---|---|---|---|---|---|---|
| T085 | 0.85 | 0.0070107 | 2.9896 | 0.00089581 | - | - |
| T120 | 1.2 | 0.006009 | 2.9189 | 0.00087613 | -14.29 % | -2.36 % |
| T160 | 1.6 | 0.0055584 | 2.8536 | 0.00085723 | -20.72 % | -4.55 % |

![Maximum total deformation](generated_reports/charts/total_deformation_by_thickness.svg)
![Derived specific stiffness](generated_reports/charts/specific_stiffness_by_thickness.svg)

Ranking (`sql/02_rank_configurations.sql`): 1.6 mm is best for deformation, stress and strain; 0.85 mm is the lightest; **1.2 mm is best for
the derived specific stiffness F/(deformation x mass)**. Full reports: [`engineering_report.md`](generated_reports/engineering_report.md),
[`data_quality_report.md`](generated_reports/data_quality_report.md) (also CSV), and every query output in `generated_reports/query_outputs/`.

## Data-quality checks

`python -m plm validate` runs 42 check codes (missing values, duplicate IDs, wrong types, units, invalid parameters, broken links,
comparability, cross-source consistency, BOM/ECR integrity, source-file hashes) and classifies findings as **error**, **warning** or **info**,
each with the affected record and a suggested correction. Source data is never modified. On the real data there are **0 errors, 11 warnings, 14 info**:

| Finding (warning) | Detail |
|---|---|
| Duplicate file content | the loose `0.85mm/Main file/WORKBENCH N MECH.wbpj` is byte-identical to the `.wbpj` inside the **1.6 mm** archive (and differs from the one in its own 0.85 mm archive) |
| Report vs solver material data | report Table 4 (flexural modulus 1973 / 5160 MPa, density 1.23 / 1.24 g/cm^3) differs from the solver deck (E 3500 / 9000 MPa, density 1.25 / 1.15 g/cm^3) |
| Report Table 5 labels | core shown as "PLA -CF" and face sheet as "PLA"; README and solver deck have a PLA core and ePA-CF face sheets |
| Unit label | report Table 6 labels equivalent elastic strain with "(mm)"; strain is dimensionless |
| README claim | "improved stiffness-to-weight ratio significantly" is not supported by F/(deformation x mass): -2.3 % from 0.85 to 1.6 mm (indicative proxy; assumes equal load) |

Checks that *confirm* consistency (they do not prove the results are physically valid): README values equal the report values rounded to the
README precision; the solver monitor's displacement component lies in the mathematically possible range for the documented total deformation;
face-sheet thickness implied by solver mass is 0.850 / 1.200 / 1.600 mm; the core mass is identical in all cases; the load derived from the deck
(pressure 0.144252 MPa x 6932.316 mm^2) is 1000.000 N, equal to the report; cases differ only in face-sheet thickness (solver, units, load, supports,
mesh counts and material data match). The repository has no experimental data and no mesh-convergence study, so physical validity remains unchecked.

## Example SQL

All queries are in [`sql/`](sql/), documented in their headers, and run on any SQLite client or with `python -m plm query <file>`.

```sql
-- Documented total deformation per configuration, best first (v_result_primary: one value per case/metric,
-- full-precision report value preferred over the rounded README value)
SELECT c.case_code, r.metric_name, r.value, r.unit, r.origin
FROM v_result_primary r JOIN simulation_case c USING (case_id)
WHERE r.metric_name = 'total_deformation' ORDER BY r.value;

-- Trace a value to its source file, archive member, line and hash
SELECT r.metric_name, r.value, r.unit, sf.rel_path, sf.archive_member, r.locator, substr(sf.sha256, 1, 12) AS sha256
FROM result_metric r JOIN source_file sf USING (source_file_id) JOIN simulation_case c USING (case_id)
WHERE c.case_code = 'SIM-T085' AND r.metric_name = 'total_mass';
--  total_mass | 41.041 | g | Simulation Files (ANSYS)/0.85mm/Main file/WORKBENCH N MECH.wbpz | .../MECH/solve.out | line 493 | ed9a991bc759

-- Missing data (never estimated)
SELECT c.case_code, r.metric_name, r.missing_reason
FROM result_metric r JOIN simulation_case c USING (case_id) WHERE r.status = 'missing' ORDER BY c.case_code, r.metric_name;

-- Same configuration + metric + component in two different solvers; returns no rows with the current single-solver data
SELECT f.config_code, a.metric_name, a.value AS value_a, b.value AS value_b
FROM v_result_primary a JOIN simulation_case ca USING (case_id)
JOIN simulation_case cb ON cb.config_id = ca.config_id AND cb.solver_id > ca.solver_id AND cb.analysis_type = ca.analysis_type
JOIN v_result_primary b ON b.case_id = cb.case_id AND b.metric_name = a.metric_name AND b.component = a.component
JOIN configuration f ON f.config_id = ca.config_id;
```

The comparison, ranking and revision queries (`sql/01`, `02`, `06`) use a pivot CTE and window functions (`RANK()`); open them for the full text.

| File | Purpose |
|---|---|
| `01_compare_thickness_configs.sql` | deformation / stress / strain by thickness, % change vs baseline |
| `02_rank_configurations.sql` | ranks by deformation, stress, strain, mass, specific stiffness |
| `03_summary_by_solver_material.sql` | available / missing results by solver and material |
| `04_missing_data.sql`, `05_quality_issues.sql` | missing results; findings of the latest validation run |
| `06_revision_tracking.sql` | revisions -> configuration -> ECR -> simulation case -> results (demonstration) |
| `07_cross_solver_comparison.sql` | cross-solver comparison, only where corresponding results exist |
| `08_traceability.sql` | configuration -> inputs / outputs -> source files, locators, SHA-256 |
| `09_bom_by_configuration.sql`, `10_change_requests.sql`, `11_change_request_history.sql` | demonstration BOM, ECR with verification results, status history |

## Known limitations

* Only **one solver** (ANSYS MAPDL 2025 R1) and one run per configuration exist, so cross-solver comparison correctly returns no rows. The query is tested with clearly labelled synthetic data only.
* Raw nodal results (`file.rst`, `SYS.mechdb`) are not parsed: stress, strain and deformation are the documented values (README, report) cross-checked against solver outputs, not re-extracted. Directional deformation, strain energy and volume are missing.
* The report is a PDF: Table 4/5/6 values are transcribed once into `data/report_values.csv` with page numbers and verified against the PDF text with `pdftotext` when available (a presence check, not a layout check).
* Stiffness-based metrics assume equal load and use the *maximum* deformation, not the deflection at the load point; treat them as indicative.
* The mesh is identical in all cases and there is no mesh-convergence study, so mesh sensitivity of the results cannot be assessed.
* The face-sheet thickness is taken from folder names and confirmed through solver mass (it assumes a solid plate of the loaded-face area); the SpaceClaim geometry files are not parsed.
* BOM, revisions and ECR are demonstration data with a deliberately small status model (no approval authority, no users, no permissions).

## Repository additions

```
plm/                 schema.sql, db.py, ingest.py, checks.py, workflow.py, report.py, cli.py, units.py
sql/                 11 documented SQL queries
data/                report_values.csv (transcribed from the PDF), demo_bom.csv (demonstration)
tests/               78 unittest tests (database, import, checks with injected errors, workflow, queries, reports)
docs/                AUDIT_AND_PLAN.md (Phase 1 audit), schema.md
                     report_appendix/: Appendix A (6 pages, project-report style) and a copy of the report with it appended
generated_reports/   sample output of `python -m plm all` (committed; the database itself is not)
```
