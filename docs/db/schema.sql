BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 7d40b95bef42

CREATE TABLE buildings (
    ose_building_id INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_buildings PRIMARY KEY (ose_building_id)
);

CREATE TABLE ml_models (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    name VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL,
    mlflow_run_id VARCHAR(64),
    artifact_path VARCHAR(255),
    is_active BOOLEAN DEFAULT false NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_ml_models PRIMARY KEY (id),
    CONSTRAINT uq_ml_models_name UNIQUE (name, version)
);

CREATE UNIQUE INDEX uq_ml_models_active_name ON ml_models (name) WHERE is_active;

CREATE TABLE users (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(255),
    full_name VARCHAR(255),
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE TABLE api_requests (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    request_id UUID NOT NULL,
    user_id BIGINT,
    method VARCHAR(10) NOT NULL,
    path VARCHAR(255) NOT NULL,
    status_code SMALLINT,
    duration_ms INTEGER,
    client_ip INET,
    request_body JSONB,
    response_body JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_api_requests PRIMARY KEY (id),
    CONSTRAINT fk_api_requests_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT uq_api_requests_request_id UNIQUE (request_id)
);

CREATE INDEX ix_api_requests_path_created ON api_requests (path, created_at);

CREATE INDEX ix_api_requests_user_created ON api_requests (user_id, created_at);

CREATE TABLE building_records_raw (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    building_id INTEGER NOT NULL,
    data_year SMALLINT NOT NULL,
    building_type VARCHAR(64),
    primary_property_type VARCHAR(64),
    property_name VARCHAR(255),
    address VARCHAR(255),
    city VARCHAR(64),
    state VARCHAR(8),
    zip_code VARCHAR(10),
    tax_parcel_identification_number VARCHAR(64),
    council_district_code SMALLINT,
    neighborhood VARCHAR(64),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    year_built SMALLINT,
    number_of_buildings DOUBLE PRECISION,
    number_of_floors SMALLINT,
    property_gfa_total INTEGER,
    property_gfa_parking INTEGER,
    property_gfa_buildings INTEGER,
    list_of_all_property_use_types TEXT,
    largest_property_use_type VARCHAR(64),
    largest_property_use_type_gfa DOUBLE PRECISION,
    second_largest_property_use_type VARCHAR(64),
    second_largest_property_use_type_gfa DOUBLE PRECISION,
    third_largest_property_use_type VARCHAR(64),
    third_largest_property_use_type_gfa DOUBLE PRECISION,
    years_energy_star_certified VARCHAR(255),
    energy_star_score DOUBLE PRECISION,
    site_eui_kbtu_sf DOUBLE PRECISION,
    site_eui_wn_kbtu_sf DOUBLE PRECISION,
    source_eui_kbtu_sf DOUBLE PRECISION,
    source_eui_wn_kbtu_sf DOUBLE PRECISION,
    site_energy_use_kbtu DOUBLE PRECISION,
    site_energy_use_wn_kbtu DOUBLE PRECISION,
    steam_use_kbtu DOUBLE PRECISION,
    electricity_kwh DOUBLE PRECISION,
    electricity_kbtu DOUBLE PRECISION,
    natural_gas_therms DOUBLE PRECISION,
    natural_gas_kbtu DOUBLE PRECISION,
    default_data BOOLEAN,
    comments TEXT,
    compliance_status VARCHAR(64),
    outlier VARCHAR(32),
    total_ghg_emissions DOUBLE PRECISION,
    ghg_emissions_intensity DOUBLE PRECISION,
    source_file VARCHAR(255) NOT NULL,
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_building_records_raw PRIMARY KEY (id),
    CONSTRAINT ck_building_records_raw_data_year_range CHECK (data_year BETWEEN 2015 AND 2100),
    CONSTRAINT fk_building_records_raw_building_id_buildings FOREIGN KEY(building_id) REFERENCES buildings (ose_building_id),
    CONSTRAINT uq_building_records_raw_building_id UNIQUE (building_id, data_year)
);

CREATE INDEX ix_building_records_raw_data_year ON building_records_raw (data_year);

CREATE TABLE building_actuals (
    record_id BIGINT NOT NULL,
    site_energy_use_kbtu DOUBLE PRECISION,
    total_ghg_emissions_tco2e DOUBLE PRECISION,
    CONSTRAINT pk_building_actuals PRIMARY KEY (record_id),
    CONSTRAINT fk_building_actuals_record_id_building_records_raw FOREIGN KEY(record_id) REFERENCES building_records_raw (id) ON DELETE CASCADE
);

CREATE TABLE building_features (
    record_id BIGINT NOT NULL,
    dataset_role VARCHAR(16) NOT NULL,
    is_training_eligible BOOLEAN NOT NULL,
    exclusion_reason VARCHAR(32),
    split VARCHAR(8),
    prep_version VARCHAR(32) NOT NULL,
    prepared_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    building_type VARCHAR(64) NOT NULL,
    primary_property_type VARCHAR(64) NOT NULL,
    neighborhood VARCHAR(64) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    year_built SMALLINT NOT NULL,
    number_of_buildings DOUBLE PRECISION,
    number_of_floors SMALLINT NOT NULL,
    property_gfa_parking INTEGER NOT NULL,
    property_gfa_buildings INTEGER NOT NULL,
    largest_property_use_type VARCHAR(64) NOT NULL,
    second_largest_property_use_type VARCHAR(64) NOT NULL,
    second_largest_property_use_type_gfa DOUBLE PRECISION,
    third_largest_property_use_type VARCHAR(64) NOT NULL,
    third_largest_property_use_type_gfa DOUBLE PRECISION,
    has_natural_gas BOOLEAN NOT NULL,
    has_steam BOOLEAN NOT NULL,
    CONSTRAINT pk_building_features PRIMARY KEY (record_id),
    CONSTRAINT ck_building_features_reason_iff_excluded CHECK ((exclusion_reason IS NOT NULL) = (dataset_role = 'training' AND NOT is_training_eligible)),
    CONSTRAINT ck_building_features_eligible_only_training CHECK (NOT is_training_eligible OR dataset_role = 'training'),
    CONSTRAINT ck_building_features_dataset_role_values CHECK (dataset_role IN ('training', 'production')),
    CONSTRAINT ck_building_features_exclusion_reason_values CHECK (exclusion_reason IN ('outlier', 'non_compliant', 'non_positive_target', 'missing_target')),
    CONSTRAINT ck_building_features_split_values CHECK (split IN ('train', 'test')),
    CONSTRAINT ck_building_features_split_iff_eligible CHECK ((split IS NOT NULL) = is_training_eligible),
    CONSTRAINT fk_building_features_record_id_building_records_raw FOREIGN KEY(record_id) REFERENCES building_records_raw (id) ON DELETE CASCADE
);

CREATE INDEX ix_building_features_role_eligible ON building_features (dataset_role, is_training_eligible);

CREATE TABLE prediction_inputs (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    api_request_id BIGINT,
    input_source VARCHAR(16) NOT NULL,
    building_record_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    building_type VARCHAR(64) NOT NULL,
    primary_property_type VARCHAR(64) NOT NULL,
    neighborhood VARCHAR(64) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    year_built SMALLINT NOT NULL,
    number_of_buildings DOUBLE PRECISION,
    number_of_floors SMALLINT NOT NULL,
    property_gfa_parking INTEGER NOT NULL,
    property_gfa_buildings INTEGER NOT NULL,
    largest_property_use_type VARCHAR(64) NOT NULL,
    second_largest_property_use_type VARCHAR(64) NOT NULL,
    second_largest_property_use_type_gfa DOUBLE PRECISION,
    third_largest_property_use_type VARCHAR(64) NOT NULL,
    third_largest_property_use_type_gfa DOUBLE PRECISION,
    has_natural_gas BOOLEAN NOT NULL,
    has_steam BOOLEAN NOT NULL,
    CONSTRAINT pk_prediction_inputs PRIMARY KEY (id),
    CONSTRAINT ck_prediction_inputs_batch_iff_no_request CHECK ((input_source = 'batch') = (api_request_id IS NULL)),
    CONSTRAINT ck_prediction_inputs_manual_without_record CHECK (input_source <> 'manual' OR building_record_id IS NULL),
    CONSTRAINT ck_prediction_inputs_record_required CHECK (input_source = 'manual' OR building_record_id IS NOT NULL),
    CONSTRAINT ck_prediction_inputs_input_source_values CHECK (input_source IN ('building_id', 'manual', 'batch')),
    CONSTRAINT fk_prediction_inputs_api_request_id_api_requests FOREIGN KEY(api_request_id) REFERENCES api_requests (id),
    CONSTRAINT fk_prediction_inputs_building_record_id_building_records_raw FOREIGN KEY(building_record_id) REFERENCES building_records_raw (id)
);

CREATE INDEX ix_prediction_inputs_api_request_id ON prediction_inputs (api_request_id);

CREATE INDEX ix_prediction_inputs_building_record_id ON prediction_inputs (building_record_id);

CREATE TABLE predictions (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    prediction_input_id BIGINT NOT NULL,
    model_id BIGINT NOT NULL,
    energy_use_kbtu DOUBLE PRECISION NOT NULL,
    ghg_emissions_tco2e DOUBLE PRECISION NOT NULL,
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_predictions PRIMARY KEY (id),
    CONSTRAINT fk_predictions_model_id_ml_models FOREIGN KEY(model_id) REFERENCES ml_models (id),
    CONSTRAINT fk_predictions_prediction_input_id_prediction_inputs FOREIGN KEY(prediction_input_id) REFERENCES prediction_inputs (id) ON DELETE CASCADE,
    CONSTRAINT uq_predictions_prediction_input_id UNIQUE (prediction_input_id, model_id)
);

CREATE INDEX ix_predictions_model_predicted ON predictions (model_id, predicted_at);

CREATE VIEW v_projected_evaluation AS
SELECT
    m.name AS model_name,
    m.version AS model_version,
    r.data_year,
    r.building_id,
    p.energy_use_kbtu AS predicted_energy_kbtu,
    a.site_energy_use_kbtu AS actual_energy_kbtu,
    p.ghg_emissions_tco2e AS predicted_ghg_tco2e,
    a.total_ghg_emissions_tco2e AS actual_ghg_tco2e,
    abs(p.energy_use_kbtu - a.site_energy_use_kbtu) AS abs_err_energy_kbtu,
    abs(p.energy_use_kbtu - a.site_energy_use_kbtu)
        / NULLIF(a.site_energy_use_kbtu, 0) AS rel_err_energy,
    abs(p.ghg_emissions_tco2e - a.total_ghg_emissions_tco2e) AS abs_err_ghg_tco2e,
    abs(p.ghg_emissions_tco2e - a.total_ghg_emissions_tco2e)
        / NULLIF(a.total_ghg_emissions_tco2e, 0) AS rel_err_ghg
FROM predictions p
JOIN ml_models m ON m.id = p.model_id
JOIN prediction_inputs i ON i.id = p.prediction_input_id
JOIN building_records_raw r ON r.id = i.building_record_id
JOIN building_actuals a ON a.record_id = r.id
WHERE i.input_source = 'batch';

INSERT INTO alembic_version (version_num) VALUES ('7d40b95bef42') RETURNING alembic_version.version_num;

COMMIT;

