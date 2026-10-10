# Data-quality report

**0 error(s), 11 warning(s), 14 information item(s).**

* **error**: the data is wrong or unusable as it stands.
* **warning**: an inconsistency or comparability problem a person must resolve; the data stays usable.
* **info**: a limitation or missing optional data worth knowing about.

> A passing check only shows that data is internally consistent. It does **not** show that the FEA results are physically valid: the repository contains no experimental data and no mesh-convergence study. Source files are never modified; every finding below is reported, not fixed.

## Checks executed

| Check | Verifies | Result |
|---|---|---|
| `FK_VIOLATION` | foreign keys resolve (links between configurations, cases, results, files) | pass |
| `TYPE_MISMATCH` | numeric columns hold numbers | pass |
| `REQUIRED_VALUE_MISSING` | required engineering values are present | pass |
| `STATUS_INCONSISTENT` | result status agrees with the stored value | pass |
| `DUPLICATE_PART_NUMBER` | part numbers are unique after normalising case, dashes and spaces | pass |
| `DUPLICATE_CONFIGURATION` | no two configurations of a product share a thickness | pass |
| `DUPLICATE_SOURCE_CONTENT` | configuration-specific files are not byte-identical across configurations | 1 warning |
| `UNIT_NOT_CANONICAL` | stored values use the canonical unit of their quantity | pass |
| `UNKNOWN_UNIT` | every printed unit is in the unit dictionary | pass |
| `UNIT_LABEL_MISMATCH` | the unit printed in the source has the dimension of the quantity | 3 warning |
| `INVALID_GEOMETRY` | thicknesses are positive | pass |
| `INVALID_MATERIAL_PARAMETER` | material properties are physically admissible (E>0, density>0, -1<nu<0.5) | pass |
| `INVALID_LOAD` | load parameters are non-zero and positive where required | pass |
| `CASE_NO_LOAD` | every case has an applied load | pass |
| `CASE_NO_BOUNDARY_CONDITION` | every case has a support / boundary condition | pass |
| `INVALID_RESULT_VALUE` | stress, deformation and strain magnitudes are non-negative; strain within small-strain range | pass |
| `CONFIG_WITHOUT_CASE` | every configuration has a simulation case | pass |
| `CASE_WITHOUT_CORE_RESULT` | every case has deformation, stress and strain results | pass |
| `CASE_MISSING_ARTIFACT` | every case links its input deck, solver log and contour images | pass |
| `RESULT_OPTIONAL_MISSING` | optional metrics (directional deformation, strain energy, volume) are available | 9 info |
| `NOT_COMPARABLE` | cases share solver, units, load, supports, mesh counts and material data (only thickness varies) | pass |
| `MATERIAL_CARD_INCONSISTENT` | one material has one set of properties in every solver deck | pass |
| `README_REPORT_ROUNDING` | README values equal the report values rounded to the README precision | pass |
| `SOLVER_VS_DOCUMENTED_DEFORMATION` | solver monitor displacement component is consistent with the documented total deformation | pass |
| `FACE_THICKNESS_MASS_MISMATCH` | face-sheet thickness implied by solver mass matches the configuration label | pass |
| `CORE_MASS_CONSTANT` | core mass is identical across configurations | pass |
| `LOAD_VS_DOCUMENTED` | load derived from the solver deck matches the load stated in the report | pass |
| `MATERIAL_DOC_VS_DECK` | material data in the report matches the data given to the solver | 4 warning |
| `MATERIAL_LABEL_MISMATCH` | material names in report tables match the solver deck | 2 warning |
| `README_CLAIM` | quantitative README claims are supported by the derived numbers | 1 warning |
| `REPORT_TRANSCRIPTION` | values in data/report_values.csv appear on the cited PDF page | pass |
| `SOURCE_FILE_CHANGED` | source files on disk still match the hashes recorded at import | pass |
| `BOM_CYCLE` | BOM has no circular parent/child relationships | pass |
| `BOM_THICKNESS_MISMATCH` | BOM face-sheet thickness equals the configuration thickness | pass |
| `BOM_MATERIAL_MISMATCH` | BOM part materials are used by the configuration | pass |
| `ECR_STATUS_HISTORY` | change-request status matches its history | pass |
| `ECR_NO_VERIFICATION` | verified/closed change requests link verification results | pass |
| `ECR_NO_ITEMS` | submitted change requests name affected items | pass |
| `REVISION_CHAIN` | a revision supersedes a revision of the same product | pass |
| `DEMONSTRATION_DATA` | demonstration data is present and labelled (information) | 1 info |
| `LIMITATION` | known limits of the available data (information) | 4 info |
| `CHECK_ABORTED` | a check could not run to completion on the data it was given | pass |

## Findings

### Error (0)

_none_

### Warning (11)

| Check | Affected record | Issue | Suggested correction |
|---|---|---|---|
| DUPLICATE_SOURCE_CONTENT | Simulation Files (ANSYS)/0.85mm/Main file/WORKBENCH N MECH.wbpj,Simulation Files (ANSYS)/1.6mm/Main file/WORKBENCH N MECH.wbpz :: WORKBENCH N MECH.wbpj | byte-identical content (sha256 28335b99bc61...) is filed under different configurations: T085,T160 | Check which configuration the file really belongs to and replace the wrong copy with the correct export. |
| MATERIAL_DOC_VS_DECK | PLA density | report Table 4 gives 1.23 g/cm^3 but the solver deck uses 1.25 for density | State the source of the solver material data and align the report table with it. |
| MATERIAL_DOC_VS_DECK | PLA flexural_modulus | report Table 4 gives 1973 MPa but the solver deck uses 3500 for youngs_modulus (different quantities: flexural vs Young's modulus; confirm which one the model intends) | State the source of the solver material data and align the report table with it. |
| MATERIAL_DOC_VS_DECK | ePA-CF density | report Table 4 gives 1.24 g/cm^3 but the solver deck uses 1.15 for density | State the source of the solver material data and align the report table with it. |
| MATERIAL_DOC_VS_DECK | ePA-CF flexural_modulus | report Table 4 gives 5160 MPa but the solver deck uses 9000 for youngs_modulus (different quantities: flexural vs Young's modulus; confirm which one the model intends) | State the source of the solver material data and align the report table with it. |
| MATERIAL_LABEL_MISMATCH | core_material_label (SIM-T085, SIM-T120, SIM-T160) | report labels the core material 'PLA -CF' but the solver deck assigns 'PLA' (report p.46 Table 5 column Core Material (rows Exp 1-3) (transcribed in data/report_values.csv line 23)) | Correct the table in the report (or the model if the report is right). |
| MATERIAL_LABEL_MISMATCH | face_sheet_material_label (SIM-T085, SIM-T120, SIM-T160) | report labels the face sheet material 'PLA' but the solver deck assigns 'ePA-CF' (report p.46 Table 5 column Face Sheet Material (rows Exp 1-3) (transcribed in data/report_values.csv line 24)) | Correct the table in the report (or the model if the report is right). |
| README_CLAIM | 'Improved stiffness-to-weight ratio significantly' | derived specific stiffness F/(deformation x mass) changes by -2.3 % from 0.85 to 1.6 mm (mass +29 %, stiffness +26 %): the claim is not supported by this metric (it assumes equal load and uses maximum deformation as the stiffness measure) | Define the stiffness-to-weight metric and report its values, or reword the claim (stiffness increases; stiffness per mass does not). |
| UNIT_LABEL_MISMATCH | result_metric#35 (SIM-T085 equivalent_elastic_strain) | source labels this dimensionless quantity with unit 'mm' (length) | Correct the unit label in the source document; the value was stored unchanged in the canonical unit. |
| UNIT_LABEL_MISMATCH | result_metric#38 (SIM-T120 equivalent_elastic_strain) | source labels this dimensionless quantity with unit 'mm' (length) | Correct the unit label in the source document; the value was stored unchanged in the canonical unit. |
| UNIT_LABEL_MISMATCH | result_metric#41 (SIM-T160 equivalent_elastic_strain) | source labels this dimensionless quantity with unit 'mm' (length) | Correct the unit label in the source document; the value was stored unchanged in the canonical unit. |

### Info (14)

| Check | Affected record | Issue | Suggested correction |
|---|---|---|---|
| DEMONSTRATION_DATA | BOM / revisions / change request | part numbers, BOM, design revisions and change requests are DEMONSTRATION data created by `python -m plm demo`, not records of a real PLM system or a real approval | Replace with real records if this is ever used operationally. |
| LIMITATION | cross-solver comparison | only one solver (ANSYS MAPDL) is present, so no cross-solver comparison is possible | Add a second solver's results for the same configurations. |
| LIMITATION | mesh sensitivity | all cases share one mesh size (same node/element counts), so mesh sensitivity of the results cannot be assessed | Run a mesh-convergence study (listed under Future Improvements in the README). |
| LIMITATION | raw solver results | file.rst / SYS.mechdb are not parsed; stress, strain and deformation are documented values (README, report) cross-checked against the solver monitor and mass, not re-extracted from the result file | Parse the result file (e.g. with pyansys) to extract nodal results. |
| LIMITATION | validity of results | the repository holds no experimental data and no mesh-convergence study; the checks here test internal consistency and comparability only and cannot show that the FEA results are physically correct | Add a mesh-convergence study and a hand calculation or test result before relying on the numbers. |
| RESULT_OPTIONAL_MISSING | SIM-T085 directional_deformation | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/0.85mm/Directional_deformation.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T085 strain_energy | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/0.85mm/Strain Energy.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T085 volume | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/0.85mm/Volume.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T120 directional_deformation | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/1.2mm/Directional_Deformation.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T120 strain_energy | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/1.2mm/Strain_energy.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T120 volume | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/1.2mm/Volume.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T160 directional_deformation | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/1.6mm/Directional_deformation.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T160 strain_energy | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/1.6mm/Strain_Energy.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
| RESULT_OPTIONAL_MISSING | SIM-T160 volume | no machine-readable numeric value in the repository; it exists only in the binary result file (not parsed) and as a contour image (Simulation Images/1.6mm/Volume.png) | Export the value as a table/CSV from ANSYS Mechanical (or parse file.rst) and add it to the repository. |
