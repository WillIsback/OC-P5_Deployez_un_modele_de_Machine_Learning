"""Tables SQLAlchemy 2.0 du schéma `p5` (spec §3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Noms de contraintes déterministes : indispensable pour des migrations stables.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureColumns:
    """Bloc des 17 features (spec §3.2), partagé par features et inputs."""

    building_type: Mapped[str] = mapped_column(String(64))
    primary_property_type: Mapped[str] = mapped_column(String(64))
    neighborhood: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    year_built: Mapped[int] = mapped_column(SmallInteger)
    number_of_buildings: Mapped[float | None] = mapped_column(Double)
    number_of_floors: Mapped[int] = mapped_column(SmallInteger)
    property_gfa_parking: Mapped[int] = mapped_column(Integer)
    property_gfa_buildings: Mapped[int] = mapped_column(Integer)
    largest_property_use_type: Mapped[str] = mapped_column(String(64))
    second_largest_property_use_type: Mapped[str] = mapped_column(String(64))
    second_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    third_largest_property_use_type: Mapped[str] = mapped_column(String(64))
    third_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    has_natural_gas: Mapped[bool] = mapped_column(Boolean)
    has_steam: Mapped[bool] = mapped_column(Boolean)


# --- Auth et traçabilité ----------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = _pk()
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()


class ApiRequest(Base):
    __tablename__ = "api_requests"
    __table_args__ = (
        Index("ix_api_requests_user_created", "user_id", "created_at"),
        Index("ix_api_requests_path_created", "path", "created_at"),
    )

    id: Mapped[int] = _pk()
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    client_ip: Mapped[str | None] = mapped_column(INET)
    request_body: Mapped[Any | None] = mapped_column(JSONB)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


# --- Dataset -----------------------------------------------------------------


class Building(Base):
    __tablename__ = "buildings"

    ose_building_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    created_at: Mapped[datetime] = _created_at()


class BuildingRecordRaw(Base):
    """Ligne CSV normalisée d'une année ; PII comprises (spec §3.3)."""

    __tablename__ = "building_records_raw"
    __table_args__ = (
        UniqueConstraint("building_id", "data_year"),
        CheckConstraint("data_year BETWEEN 2015 AND 2100", name="data_year_range"),
        Index("ix_building_records_raw_data_year", "data_year"),
    )

    id: Mapped[int] = _pk()
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.ose_building_id"))
    data_year: Mapped[int] = mapped_column(SmallInteger)
    building_type: Mapped[str | None] = mapped_column(String(64))
    primary_property_type: Mapped[str | None] = mapped_column(String(64))
    property_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(8))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    tax_parcel_identification_number: Mapped[str | None] = mapped_column(String(64))
    council_district_code: Mapped[int | None] = mapped_column(SmallInteger)
    neighborhood: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    year_built: Mapped[int | None] = mapped_column(SmallInteger)
    number_of_buildings: Mapped[float | None] = mapped_column(Double)
    number_of_floors: Mapped[int | None] = mapped_column(SmallInteger)
    property_gfa_total: Mapped[int | None] = mapped_column(Integer)
    property_gfa_parking: Mapped[int | None] = mapped_column(Integer)
    property_gfa_buildings: Mapped[int | None] = mapped_column(Integer)
    list_of_all_property_use_types: Mapped[str | None] = mapped_column(Text)
    largest_property_use_type: Mapped[str | None] = mapped_column(String(64))
    largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    second_largest_property_use_type: Mapped[str | None] = mapped_column(String(64))
    second_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    third_largest_property_use_type: Mapped[str | None] = mapped_column(String(64))
    third_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    years_energy_star_certified: Mapped[str | None] = mapped_column(String(255))
    energy_star_score: Mapped[float | None] = mapped_column(Double)
    site_eui_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    site_eui_wn_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    source_eui_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    source_eui_wn_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    site_energy_use_kbtu: Mapped[float | None] = mapped_column(Double)
    site_energy_use_wn_kbtu: Mapped[float | None] = mapped_column(Double)
    steam_use_kbtu: Mapped[float | None] = mapped_column(Double)
    electricity_kwh: Mapped[float | None] = mapped_column(Double)
    electricity_kbtu: Mapped[float | None] = mapped_column(Double)
    natural_gas_therms: Mapped[float | None] = mapped_column(Double)
    natural_gas_kbtu: Mapped[float | None] = mapped_column(Double)
    default_data: Mapped[bool | None] = mapped_column(Boolean)
    comments: Mapped[str | None] = mapped_column(Text)
    compliance_status: Mapped[str | None] = mapped_column(String(64))
    outlier: Mapped[str | None] = mapped_column(String(32))
    total_ghg_emissions: Mapped[float | None] = mapped_column(Double)
    ghg_emissions_intensity: Mapped[float | None] = mapped_column(Double)
    source_file: Mapped[str] = mapped_column(String(255))
    ingested_at: Mapped[datetime] = _created_at()


class BuildingFeatures(FeatureColumns, Base):
    """Deuxième temps de la préparation : uniquement le périmètre du modèle."""

    __tablename__ = "building_features"
    __table_args__ = (
        CheckConstraint(
            "dataset_role IN ('training', 'production')", name="dataset_role_values"
        ),
        CheckConstraint("split IN ('train', 'test')", name="split_values"),
        CheckConstraint(
            "exclusion_reason IN ('outlier', 'non_compliant', "
            "'non_positive_target', 'missing_target')",
            name="exclusion_reason_values",
        ),
        CheckConstraint(
            "NOT is_training_eligible OR dataset_role = 'training'",
            name="eligible_only_training",
        ),
        CheckConstraint(
            "(split IS NOT NULL) = is_training_eligible", name="split_iff_eligible"
        ),
        CheckConstraint(
            "(exclusion_reason IS NOT NULL) = "
            "(dataset_role = 'training' AND NOT is_training_eligible)",
            name="reason_iff_excluded",
        ),
        Index(
            "ix_building_features_role_eligible", "dataset_role", "is_training_eligible"
        ),
    )

    record_id: Mapped[int] = mapped_column(
        ForeignKey("building_records_raw.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_role: Mapped[str] = mapped_column(String(16))
    is_training_eligible: Mapped[bool] = mapped_column(Boolean)
    exclusion_reason: Mapped[str | None] = mapped_column(String(32))
    split: Mapped[str | None] = mapped_column(String(8))
    prep_version: Mapped[str] = mapped_column(String(32))
    prepared_at: Mapped[datetime] = _created_at()


class BuildingActual(Base):
    """Cibles réelles, isolées des features (jamais lues par l'API)."""

    __tablename__ = "building_actuals"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("building_records_raw.id", ondelete="CASCADE"), primary_key=True
    )
    site_energy_use_kbtu: Mapped[float | None] = mapped_column(Double)
    total_ghg_emissions_tco2e: Mapped[float | None] = mapped_column(Double)


# --- Modèle ------------------------------------------------------------------


class MlModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        # Une seule version active par nom de modèle.
        Index(
            "uq_ml_models_active_name",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    artifact_path: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()


class PredictionInput(FeatureColumns, Base):
    """Snapshot figé de ce qui est envoyé au modèle."""

    __tablename__ = "prediction_inputs"
    __table_args__ = (
        CheckConstraint(
            "input_source IN ('building_id', 'manual', 'batch')",
            name="input_source_values",
        ),
        CheckConstraint(
            "input_source = 'manual' OR building_record_id IS NOT NULL",
            name="record_required",
        ),
        CheckConstraint(
            "input_source <> 'manual' OR building_record_id IS NULL",
            name="manual_without_record",
        ),
        CheckConstraint(
            "(input_source = 'batch') = (api_request_id IS NULL)",
            name="batch_iff_no_request",
        ),
        Index("ix_prediction_inputs_api_request_id", "api_request_id"),
        Index("ix_prediction_inputs_building_record_id", "building_record_id"),
    )

    id: Mapped[int] = _pk()
    # Pas de ON DELETE SET NULL : incompatible avec le CHECK batch_iff_no_request.
    api_request_id: Mapped[int | None] = mapped_column(ForeignKey("api_requests.id"))
    input_source: Mapped[str] = mapped_column(String(16))
    building_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("building_records_raw.id")
    )
    created_at: Mapped[datetime] = _created_at()


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("prediction_input_id", "model_id"),
        Index("ix_predictions_model_predicted", "model_id", "predicted_at"),
    )

    id: Mapped[int] = _pk()
    prediction_input_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_inputs.id", ondelete="CASCADE")
    )
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id"))
    energy_use_kbtu: Mapped[float] = mapped_column(Double)
    ghg_emissions_tco2e: Mapped[float] = mapped_column(Double)
    predicted_at: Mapped[datetime] = _created_at()
