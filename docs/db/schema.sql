BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- État final (head 3b8e1f6a42c7) : tables conservées puis tables du schéma simplifié

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

CREATE TABLE buildings (
    id INTEGER NOT NULL,
    property_name VARCHAR(255),
    address VARCHAR(255),
    zip_code VARCHAR(10),
    neighborhood VARCHAR(64),
    building_type VARCHAR(64),
    primary_property_type VARCHAR(64),
    split VARCHAR(8),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_buildings PRIMARY KEY (id),
    CONSTRAINT ck_buildings_split_values CHECK (split IN ('train', 'test'))
);

CREATE TABLE building_years (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    building_id INTEGER NOT NULL,
    data_year SMALLINT NOT NULL,
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
    exclusion_reason VARCHAR(32),
    prep_version VARCHAR(32) NOT NULL,
    prepared_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_building_years PRIMARY KEY (id),
    CONSTRAINT ck_building_years_data_year_range CHECK (data_year BETWEEN 2015 AND 2100),
    CONSTRAINT ck_building_years_exclusion_reason_values CHECK (exclusion_reason IN ('outlier', 'non_compliant', 'non_positive_target', 'missing_target', 'aberrant_energy', 'aberrant_emissions')),
    CONSTRAINT fk_building_years_building_id_buildings FOREIGN KEY(building_id) REFERENCES buildings (id),
    CONSTRAINT uq_building_years_building_id UNIQUE (building_id, data_year)
);

CREATE INDEX ix_building_years_data_year ON building_years (data_year);

CREATE TABLE building_actuals (
    building_year_id BIGINT NOT NULL,
    site_energy_use_kbtu DOUBLE PRECISION,
    total_ghg_emissions_tco2e DOUBLE PRECISION,
    CONSTRAINT pk_building_actuals PRIMARY KEY (building_year_id),
    CONSTRAINT fk_building_actuals_building_year_id_building_years FOREIGN KEY(building_year_id) REFERENCES building_years (id) ON DELETE CASCADE
);

CREATE TABLE predictions (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    api_request_id BIGINT,
    building_year_id BIGINT,
    model_id BIGINT NOT NULL,
    input_features JSONB NOT NULL,
    energy_use_kbtu DOUBLE PRECISION NOT NULL,
    ghg_emissions_tco2e DOUBLE PRECISION NOT NULL,
    predicted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_predictions PRIMARY KEY (id),
    CONSTRAINT ck_predictions_has_origin CHECK (api_request_id IS NOT NULL OR building_year_id IS NOT NULL),
    CONSTRAINT fk_predictions_api_request_id_api_requests FOREIGN KEY(api_request_id) REFERENCES api_requests (id),
    CONSTRAINT fk_predictions_building_year_id_building_years FOREIGN KEY(building_year_id) REFERENCES building_years (id),
    CONSTRAINT fk_predictions_model_id_ml_models FOREIGN KEY(model_id) REFERENCES ml_models (id)
);

CREATE INDEX ix_predictions_model_predicted ON predictions (model_id, predicted_at);

CREATE INDEX ix_predictions_api_request_id ON predictions (api_request_id);

CREATE INDEX ix_predictions_building_year_id ON predictions (building_year_id);

CREATE UNIQUE INDEX uq_predictions_batch ON predictions (building_year_id, model_id) WHERE api_request_id IS NULL;

CREATE VIEW v_projected_evaluation AS
SELECT
    m.name AS model_name,
    m.version AS model_version,
    y.data_year,
    y.building_id,
    y.exclusion_reason,
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
JOIN building_years y ON y.id = p.building_year_id
JOIN building_actuals a ON a.building_year_id = y.id
WHERE p.api_request_id IS NULL;

INSERT INTO alembic_version (version_num) VALUES ('3b8e1f6a42c7');

COMMIT;
