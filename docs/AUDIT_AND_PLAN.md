# Phase 1 audit and implementation plan

Audit of the repository as received (branch point `40d8fab`, `main` and the working branch were identical and the
working tree was clean, so there was no uncommitted work to protect). All changes are made on branch
`claude/honeycomb-fea-plm-system-7by5ma`; `main` is untouched, which serves as the backup.

## 1. What the repository contains

| Path | Content | Machine-readable? |
|---|---|---|
| `README.md` | Objective, method, material table, **results table** (deformation / von Mises stress / elastic strain per thickness), qualitative claims | Yes (Markdown table) |
| `Report/MAJOR PROJECT REPORT (1).pdf` | 68-page project report; Table 4 (material data, p.37), Table 5 (case table, p.46), Fig. 11/12 captions (1000 N load, p.46-47), **Table 6 (results, p.61)** | Text layer yes; tables need transcription |
| `Simulation Files (ANSYS)/<t>mm/Main file/WORKBENCH N MECH.wbpz` (x3) | Zipped ANSYS Workbench projects | Yes, see below |
| `Simulation Files (ANSYS)/0.85mm/Main file/WORKBENCH N MECH.wbpj` | Loose Workbench project XML | Yes |
| `Simulation Files (ANSYS)/<t>mm/Geometry/*.scdocx` (x3) | SpaceClaim CAD (zip with Parasolid) | No (binary geometry) |
| `Simulation Images/<t>mm/*.png`, `Common Conditions/*.png` | Mechanical screenshots (contours, boundary conditions) | No (image only, no OCR) |

There is **no code, no CSV, no database, no dependency manifest and no tests** in the repository. The technology stack
is "ANSYS Workbench / Mechanical / SpaceClaim" (README) with Markdown documentation.

### Inside each `.wbpz` (verified by unpacking to a scratch directory, nothing written to the repo)

| Member | Extractable data | Used |
|---|---|---|
| `dp0/SYS/MECH/ds.dat` | MAPDL input deck: material cards (`MP,EX/NUXY/DENS`), element-type-to-material map, fixed-support node set, surface-pressure load (`sfe,...,pres`) and the 195 `SURF154` load elements with node coordinates | Yes |
| `dp0/SYS/MECH/solve.out` | Solver release/build, run date, node/element counts, total and per-element-type mass, warning/error counts, solver type | Yes |
| `dp0/SYS/MECH/file.mntr` | Solution monitor: max displacement component (`MxDs`) | Yes |
| `dp0/SYS/MECH/MatML.xml` | Material name to `UVID` map (which `MP` card is PLA / ePA-CF) | Yes |
| `WORKBENCH N MECH.wbpj` | Project save timestamp (UTC), Workbench version | Yes |
| `dp0/SYS/MECH/file.rst`, `dp0/global/MECH/SYS.mechdb` | Binary result / HDF5 database (the only place raw nodal results live) | **No** (needs ANSYS/pyansys/h5py), registered by hash only |

### What is reliably extractable

* **Configuration**: face-sheet thickness 0.85 / 1.2 / 1.6 mm (folder names, README, report, and independently from solver mass, see below).
* **Solver input**: static structural, ANSYS MAPDL 2025 R1 build 25.1, N-mm-tonne-s units, PLA core (E 3500 MPa, nu 0.36, 1.25 g/cm3),
  ePA-CF face sheets (E 9000 MPa, nu 0.35, 1.15 g/cm3), fixed support (642 nodes), pressure 0.14425 MPa on 195 surface elements
  (loaded area computed from the deck = 6932.316 mm2, resultant 1000.000 N, equal to the 1000 N in the report), mesh 14009 nodes / 2093 solid elements.
* **Solver output**: total mass (41.04 / 46.62 / 53.00 g), max displacement component from `file.mntr`.
* **Documented results** (not recomputed): total deformation, equivalent (von Mises) stress, equivalent elastic strain, from README (rounded) and report Table 6 (full precision).

### What is NOT available (recorded as missing, never invented)

* Numeric directional deformation, strain energy and volume values (only contour images exist).
* Raw nodal results (`file.rst`, `.mechdb` not parsed).
* A second solver or a second run per configuration: **no cross-solver comparison is possible** with this data.
* Any genuine historical revision / ECR / BOM record: the repository only holds a parametric study. Part numbers, the BOM,
  design revisions and the change request in this extension are **demonstration data**, labelled as such everywhere.
* Mesh-convergence study (listed under "Future Improvements" in the README).

### Findings from the audit that the data-quality checks must reproduce

1. The loose `0.85mm/Main file/WORKBENCH N MECH.wbpj` is byte-identical to the `.wbpj` inside the **1.6 mm** archive (and differs from the one in its own 0.85 mm archive).
2. Report Table 4 material data (flexural modulus 1973 / 5160 MPa, density 1.23 / 1.24 g/cm3) differs from the values in the solver deck (E 3500 / 9000 MPa, density 1.25 / 1.15 g/cm3).
3. Report Table 5 labels the core "PLA -CF" and the face sheet "PLA"; the README and the solver deck have PLA core and ePA-CF face sheets.
4. Report Table 6 labels equivalent elastic strain with unit "(mm)"; strain is dimensionless. Stress is printed in Pa, the README uses MPa (unit conversion needed).
5. README claims "improved stiffness-to-weight ratio significantly"; with a stiffness proxy of F/(max deformation) per unit mass this is not supported (see engineering report).

## 2. Technology decisions

* **Python 3 standard library only** (`sqlite3`, `csv`, `zipfile`, `hashlib`, `xml.etree`, `argparse`, `unittest`). `pytest`, `pandas`
  and `matplotlib` are not required; charts are written as plain SVG.
* **SQLite** database, rebuilt from source on demand and not committed (`build/` is git-ignored).
* Optional: `pdftotext` (poppler) is used, if present, to confirm that every transcribed report value really appears on the cited PDF page.

## 3. Files added (no existing file is overwritten; `README.md` gets an appended section only)

```
plm/                  package: schema.sql, db.py, ingest.py, checks.py, workflow.py, report.py, cli.py, units.py
sql/                  11 documented SQL query files
data/report_values.csv  values transcribed from the PDF (page-referenced, verbatim "as printed" strings)
data/demo_bom.csv     DEMONSTRATION BOM (illustrative part numbers)
tests/                unittest suites
docs/                 this file, schema.md
generated_reports/    sample generated output (markdown, CSV, SVG charts)
README.md             appended section (existing content untouched)
.gitignore            ignores build/ and __pycache__
```
