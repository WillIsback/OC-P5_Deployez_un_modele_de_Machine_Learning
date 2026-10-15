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
    """Bloc des 17 features du modèle."""

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
    """Identité d'un bâtiment ; `split` le range côté entraînement ou « jamais vu »."""

    __tablename__ = "buildings"
    __table_args__ = (
        CheckConstraint("split IN ('train', 'test')", name="split_values"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    property_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    neighborhood: Mapped[str | None] = mapped_column(String(64))
    building_type: Mapped[str | None] = mapped_column(String(64))
    primary_property_type: Mapped[str | None] = mapped_column(String(64))
    # NULL = jamais vu par l'entraînement (ni train ni test).
    split: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = _created_at()


class BuildingYear(FeatureColumns, Base):
    """Features d'un bâtiment pour une année : uniquement le périmètre du modèle."""

    __tablename__ = "building_years"
    __table_args__ = (
        UniqueConstraint("building_id", "data_year"),
        CheckConstraint("data_year BETWEEN 2015 AND 2100", name="data_year_range"),
        CheckConstraint(
            "exclusion_reason IN ('outlier', 'non_compliant', "
            "'non_positive_target', 'missing_target', "
            "'aberrant_energy', 'aberrant_emissions')",
            name="exclusion_reason_values",
        ),
        Index("ix_building_years_data_year", "data_year"),
    )

    id: Mapped[int] = _pk()
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"))
    data_year: Mapped[int] = mapped_column(SmallInteger)
    exclusion_reason: Mapped[str | None] = mapped_column(String(32))
    prep_version: Mapped[str] = mapped_column(String(32))
    prepared_at: Mapped[datetime] = _created_at()


class BuildingActual(Base):
    """Cibles réelles, isolées des features (jamais lues par l'API)."""

    __tablename__ = "building_actuals"

    building_year_id: Mapped[int] = mapped_column(
        ForeignKey("building_years.id", ondelete="CASCADE"), primary_key=True
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


class Prediction(Base):
    """Une prédiction d'un modèle, avec l'entrée figée qui l'a produite.

    Origine déduite des colonnes : requête + année = appel API par bâtiment ;
    requête seule = saisie libre ; année seule = évaluation par lot.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint(
            "api_request_id IS NOT NULL OR building_year_id IS NOT NULL",
            name="has_origin",
        ),
        Index("ix_predictions_model_predicted", "model_id", "predicted_at"),
        Index("ix_predictions_api_request_id", "api_request_id"),
        Index("ix_predictions_building_year_id", "building_year_id"),
        # Une seule prédiction par lot (hors API) pour une ligne d'année et un modèle.
        Index(
            "uq_predictions_batch",
            "building_year_id",
            "model_id",
            unique=True,
            postgresql_where=text("api_request_id IS NULL"),
        ),
    )

    id: Mapped[int] = _pk()
    api_request_id: Mapped[int | None] = mapped_column(ForeignKey("api_requests.id"))
    building_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("building_years.id")
    )
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id"))
    input_features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    energy_use_kbtu: Mapped[float] = mapped_column(Double)
    ghg_emissions_tco2e: Mapped[float] = mapped_column(Double)
    predicted_at: Mapped[datetime] = _created_at()
