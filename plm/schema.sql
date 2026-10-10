-- Engineering data model for the honeycomb sandwich-panel FEA project.
-- Design rule: constraints guarantee *structural* integrity (keys, enums, NOT NULL on identifiers).
-- *Physical* validity (thickness > 0, E > 0, units, ...) is deliberately NOT a CHECK constraint:
-- as-received data must be storable so that plm/checks.py can report it instead of the import crashing.
-- Where a table has `origin`/`basis`: 'source' / 'solver_file' / 'documented' = taken from repository files,
-- 'derived' = calculated from those, 'demonstration' = illustrative data created by this tool.

CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Dictionary of every physical quantity the database stores, with its canonical unit.
CREATE TABLE quantity_def (
    quantity       TEXT PRIMARY KEY,
    canonical_unit TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    is_core_result INTEGER NOT NULL DEFAULT 0 CHECK (is_core_result IN (0, 1)),
    description    TEXT NOT NULL
);

-- ---------------------------------------------------------------- project / product / material
CREATE TABLE project (
    project_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);
CREATE TABLE product (
    product_id   INTEGER PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES project(project_id),
    product_code TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL
);
CREATE TABLE material (
    material_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- ---------------------------------------------------------------- source files (traceability backbone)
CREATE TABLE source_file (
    source_file_id INTEGER PRIMARY KEY,
    rel_path       TEXT NOT NULL,                 -- relative to the repository root, '/' separators
    archive_member TEXT NOT NULL DEFAULT '',      -- path inside a .wbpz, '' for a plain file
    sha256         TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    file_kind      TEXT NOT NULL,                 -- readme, report_pdf, ansys_archive, archive_member, contour_image, ...
    UNIQUE (rel_path, archive_member)
);
CREATE INDEX ix_source_file_sha ON source_file(sha256);

-- ---------------------------------------------------------------- design configurations, BOM, revisions
CREATE TABLE configuration (
    config_id                INTEGER PRIMARY KEY,
    product_id               INTEGER NOT NULL REFERENCES product(product_id),
    config_code              TEXT NOT NULL UNIQUE,     -- e.g. T085 = 0.85 mm face sheet
    face_sheet_thickness_mm  REAL,
    core_material_id         INTEGER REFERENCES material(material_id),
    face_sheet_material_id   INTEGER REFERENCES material(material_id),
    thickness_source         TEXT
);
CREATE INDEX ix_configuration_product ON configuration(product_id);

CREATE TABLE part (                                    -- DEMONSTRATION part numbers (see data/demo_bom.csv)
    part_id       INTEGER PRIMARY KEY,
    part_number   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    part_type     TEXT NOT NULL CHECK (part_type IN ('assembly', 'component')),
    material_id   INTEGER REFERENCES material(material_id),
    thickness_mm  REAL,
    basis         TEXT NOT NULL DEFAULT 'demonstration' CHECK (basis IN ('source', 'demonstration'))
);
CREATE TABLE bom_line (
    bom_line_id    INTEGER PRIMARY KEY,
    config_id      INTEGER NOT NULL REFERENCES configuration(config_id),
    parent_part_id INTEGER NOT NULL REFERENCES part(part_id),
    child_part_id  INTEGER NOT NULL REFERENCES part(part_id),
    quantity       REAL NOT NULL,
    find_no        INTEGER,
    CHECK (parent_part_id <> child_part_id),
    UNIQUE (config_id, parent_part_id, child_part_id)
);
CREATE INDEX ix_bom_config ON bom_line(config_id);
CREATE INDEX ix_bom_parent ON bom_line(parent_part_id);
CREATE INDEX ix_bom_child  ON bom_line(child_part_id);

CREATE TABLE change_request (
    ecr_id      INTEGER PRIMARY KEY,
    ecr_code    TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN
                ('DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'IMPLEMENTED', 'VERIFIED', 'CLOSED', 'REJECTED')),
    basis       TEXT NOT NULL DEFAULT 'demonstration' CHECK (basis IN ('source', 'demonstration'))
);
CREATE TABLE design_revision (
    rev_id          INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES product(product_id),
    rev_label       TEXT NOT NULL,
    config_id       INTEGER NOT NULL REFERENCES configuration(config_id),
    ecr_id          INTEGER REFERENCES change_request(ecr_id),
    supersedes_rev_id INTEGER REFERENCES design_revision(rev_id),
    description     TEXT,
    basis           TEXT NOT NULL DEFAULT 'demonstration' CHECK (basis IN ('source', 'demonstration')),
    UNIQUE (product_id, rev_label)
);
CREATE INDEX ix_revision_config ON design_revision(config_id);
CREATE INDEX ix_revision_ecr    ON design_revision(ecr_id);

CREATE TABLE ecr_status_history (
    history_id  INTEGER PRIMARY KEY,
    ecr_id      INTEGER NOT NULL REFERENCES change_request(ecr_id),
    seq         INTEGER NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    changed_utc TEXT NOT NULL,
    note        TEXT,
    UNIQUE (ecr_id, seq)
);

-- ---------------------------------------------------------------- simulation
CREATE TABLE solver (
    solver_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    version   TEXT NOT NULL,
    build     TEXT,
    UNIQUE (name, version)
);
CREATE TABLE simulation_case (
    case_id           INTEGER PRIMARY KEY,
    case_code         TEXT NOT NULL UNIQUE,
    config_id         INTEGER NOT NULL REFERENCES configuration(config_id),
    solver_id         INTEGER NOT NULL REFERENCES solver(solver_id),
    analysis_type     TEXT NOT NULL,
    solver_run_local  TEXT,        -- as printed in solve.out; the time zone is not recorded in the file
    project_saved_utc TEXT         -- from the Workbench project file
);
CREATE INDEX ix_case_config ON simulation_case(config_id);
CREATE INDEX ix_case_solver ON simulation_case(solver_id);

-- an ECR points at exactly one part, configuration or simulation case per row
CREATE TABLE ecr_item (
    ecr_item_id INTEGER PRIMARY KEY,
    ecr_id      INTEGER NOT NULL REFERENCES change_request(ecr_id),
    role        TEXT NOT NULL CHECK (role IN ('affected', 'proposed', 'verification')),
    part_id     INTEGER REFERENCES part(part_id),
    config_id   INTEGER REFERENCES configuration(config_id),
    case_id     INTEGER REFERENCES simulation_case(case_id),
    note        TEXT,
    CHECK ((part_id IS NOT NULL) + (config_id IS NOT NULL) + (case_id IS NOT NULL) = 1)
);
CREATE INDEX ix_ecr_item_ecr ON ecr_item(ecr_id);

CREATE TABLE simulation_input (            -- analysis settings, mesh, loads, boundary conditions, material assignment
    input_id       INTEGER PRIMARY KEY,
    case_id        INTEGER NOT NULL REFERENCES simulation_case(case_id),
    category       TEXT NOT NULL CHECK (category IN
                   ('analysis', 'mesh', 'load', 'boundary_condition', 'material_assignment')),
    param_name     TEXT NOT NULL,
    value_num      REAL,
    value_text     TEXT,
    unit           TEXT,
    origin         TEXT NOT NULL CHECK (origin IN ('solver_file', 'documented', 'derived')),
    derivation     TEXT,                   -- formula and assumptions for derived values
    source_file_id INTEGER NOT NULL REFERENCES source_file(source_file_id),
    locator        TEXT NOT NULL,          -- line / table / key inside the source
    UNIQUE (case_id, param_name, origin, source_file_id, locator)
);
CREATE INDEX ix_input_case ON simulation_input(case_id, param_name);
CREATE INDEX ix_input_source ON simulation_input(source_file_id);

CREATE TABLE material_property (
    property_id    INTEGER PRIMARY KEY,
    material_id    INTEGER NOT NULL REFERENCES material(material_id),
    case_id        INTEGER REFERENCES simulation_case(case_id),   -- set for solver-deck values, NULL for report values
    quantity       TEXT NOT NULL REFERENCES quantity_def(quantity),
    value          REAL,
    unit           TEXT NOT NULL,
    original_value REAL,
    original_unit  TEXT,
    origin         TEXT NOT NULL CHECK (origin IN ('solver_file', 'documented')),
    source_file_id INTEGER NOT NULL REFERENCES source_file(source_file_id),
    locator        TEXT NOT NULL,
    UNIQUE (material_id, quantity, origin, source_file_id, locator)
);
CREATE INDEX ix_matprop_material ON material_property(material_id, quantity);
CREATE INDEX ix_matprop_source ON material_property(source_file_id);

CREATE TABLE result_metric (
    result_id      INTEGER PRIMARY KEY,
    case_id        INTEGER NOT NULL REFERENCES simulation_case(case_id),
    metric_name    TEXT NOT NULL REFERENCES quantity_def(quantity),
    statistic      TEXT NOT NULL CHECK (statistic IN ('max', 'total')),
    component      TEXT NOT NULL DEFAULT 'assembly',     -- assembly | core | face_sheet_1 | face_sheet_2
    value          REAL,                                  -- canonical unit (quantity_def.canonical_unit)
    unit           TEXT NOT NULL,
    original_value REAL,                                  -- exactly as read from the source
    original_unit  TEXT,
    printed_text   TEXT,                                  -- the digits as printed (documented values), for rounding checks
    status         TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'missing')),
    missing_reason TEXT,
    origin         TEXT NOT NULL CHECK (origin IN ('documented', 'solver_file')),
    source_file_id INTEGER NOT NULL REFERENCES source_file(source_file_id),
    locator        TEXT NOT NULL,
    UNIQUE (case_id, metric_name, statistic, component, source_file_id, locator)
);
CREATE INDEX ix_result_case_metric ON result_metric(case_id, metric_name);
CREATE INDEX ix_result_source ON result_metric(source_file_id);          -- "which values came from this file?"

-- every file that belongs to a configuration / case, with its role
CREATE TABLE artifact_link (
    link_id        INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES source_file(source_file_id),
    config_id      INTEGER NOT NULL REFERENCES configuration(config_id),
    case_id        INTEGER REFERENCES simulation_case(case_id),
    role           TEXT NOT NULL,
    UNIQUE (source_file_id, config_id, role)
);
CREATE INDEX ix_link_config ON artifact_link(config_id);
CREATE INDEX ix_link_case   ON artifact_link(case_id);

-- ---------------------------------------------------------------- data quality
CREATE TABLE validation_run (
    run_id      INTEGER PRIMARY KEY,
    started_utc TEXT NOT NULL,
    n_error     INTEGER NOT NULL DEFAULT 0,
    n_warning   INTEGER NOT NULL DEFAULT 0,
    n_info      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE validation_issue (
    issue_id             INTEGER PRIMARY KEY,
    run_id               INTEGER NOT NULL REFERENCES validation_run(run_id),
    check_code           TEXT NOT NULL,
    severity             TEXT NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    table_name           TEXT,
    record_id            TEXT,
    source_file_id       INTEGER REFERENCES source_file(source_file_id),
    message              TEXT NOT NULL,
    suggested_correction TEXT NOT NULL
);
CREATE INDEX ix_issue_run ON validation_issue(run_id, severity);

-- ---------------------------------------------------------------- views
-- One value per (case, metric, statistic, component): report (full precision) beats README (rounded).
CREATE VIEW v_result_primary AS
SELECT * FROM (
    SELECT r.*, sf.rel_path, sf.file_kind,
           ROW_NUMBER() OVER (
               PARTITION BY r.case_id, r.metric_name, r.statistic, r.component
               ORDER BY CASE sf.file_kind WHEN 'report_pdf' THEN 1 WHEN 'readme' THEN 3 ELSE 2 END, r.result_id
           ) AS rn
    FROM result_metric r JOIN source_file sf USING (source_file_id)
    WHERE r.status = 'ok'
) WHERE rn = 1;

-- ---------------------------------------------------------------- quantity dictionary
INSERT INTO quantity_def (quantity, canonical_unit, dimension, is_core_result, description) VALUES
 ('total_deformation',         'mm',     'length',      1, 'Maximum total (vector magnitude) deformation'),
 ('equivalent_stress',         'MPa',    'pressure',    1, 'Maximum equivalent (von Mises) stress'),
 ('equivalent_elastic_strain', '1',      'dimensionless', 1, 'Maximum equivalent elastic strain'),
 ('directional_deformation',   'mm',     'length',      0, 'Maximum directional deformation'),
 ('strain_energy',             'mJ',     'energy',      0, 'Strain energy'),
 ('volume',                    'mm^3',   'volume',      0, 'Volume (check)'),
 ('total_mass',                'g',      'mass',        0, 'Total model mass from the solver mass summary'),
 ('element_type_mass',         'g',      'mass',        0, 'Mass of one element type (body) from the solver mass summary'),
 ('max_displacement_component','mm',     'length',      0, 'Nodal displacement component of largest magnitude from the solution monitor (file.mntr MxDs), signed as printed'),
 ('youngs_modulus',            'MPa',    'pressure',    0, 'Young''s modulus'),
 ('poissons_ratio',            '1',      'dimensionless', 0, 'Poisson''s ratio'),
 ('density',                   'g/cm^3', 'density',     0, 'Mass density'),
 ('flexural_modulus',          'MPa',    'pressure',    0, 'Flexural modulus'),
 ('tensile_strength',          'MPa',    'pressure',    0, 'Tensile strength'),
 ('flexural_strength',         'MPa',    'pressure',    0, 'Flexural strength'),
 ('shear_modulus',             'MPa',    'pressure',    0, 'Shear modulus'),
 ('izod_impact_strength',      'kJ/m^2', 'energy_per_area', 0, 'Izod impact strength'),
 ('applied_pressure',          'MPa',    'pressure',    0, 'Surface pressure applied through surface-effect elements (negative = against the surface normal)'),
 ('loaded_area',               'mm^2',   'area',        0, 'Area carrying the applied pressure'),
 ('applied_force',             'N',      'force',       0, 'Resultant of the applied load'),
 ('node_count',                '1',      'count',       0, 'Number of nodes'),
 ('solid_element_count',       '1',      'count',       0, 'Number of solid elements'),
 ('total_element_count',       '1',      'count',       0, 'Number of elements of all types');

INSERT INTO schema_info (key, value) VALUES ('schema_version', '1');
