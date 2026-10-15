"""schema simplifie

Revision ID: 3b8e1f6a42c7
Revises: 7d40b95bef42
Create Date: 2026-10-15 12:00:00.000000

Migration destructive : le brut, les features, les entrées de prédiction et les
anciennes prédictions sont supprimés ; les données se reconstruisent depuis les
CSV (`app.db.ingest`). `users`, `api_requests` et `ml_models` sont conservées.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.views import PROJECTED_EVALUATION_VIEW

# revision identifiers, used by Alembic.
revision: str = "3b8e1f6a42c7"
down_revision: str | Sequence[str] | None = "7d40b95bef42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_projected_evaluation")
    for table in (
        "predictions",
        "prediction_inputs",
        "building_actuals",
        "building_features",
        "building_records_raw",
        "buildings",
    ):
        op.drop_table(table)

    op.create_table(
        "buildings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("property_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("zip_code", sa.String(length=10), nullable=True),
        sa.Column("neighborhood", sa.String(length=64), nullable=True),
        sa.Column("building_type", sa.String(length=64), nullable=True),
        sa.Column("primary_property_type", sa.String(length=64), nullable=True),
        sa.Column("split", sa.String(length=8), nullable=True),
        _created_at("created_at"),
        sa.CheckConstraint(
            "split IN ('train', 'test')", name=op.f("ck_buildings_split_values")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buildings")),
    )
    op.create_table(
        "building_years",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=False),
        sa.Column("data_year", sa.SmallInteger(), nullable=False),
        sa.Column("building_type", sa.String(length=64), nullable=False),
        sa.Column("primary_property_type", sa.String(length=64), nullable=False),
        sa.Column("neighborhood", sa.String(length=64), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("year_built", sa.SmallInteger(), nullable=False),
        sa.Column("number_of_buildings", sa.Double(), nullable=True),
        sa.Column("number_of_floors", sa.SmallInteger(), nullable=False),
        sa.Column("property_gfa_parking", sa.Integer(), nullable=False),
        sa.Column("property_gfa_buildings", sa.Integer(), nullable=False),
        sa.Column("largest_property_use_type", sa.String(length=64), nullable=False),
        sa.Column(
            "second_largest_property_use_type", sa.String(length=64), nullable=False
        ),
        sa.Column("second_largest_property_use_type_gfa", sa.Double(), nullable=True),
        sa.Column(
            "third_largest_property_use_type", sa.String(length=64), nullable=False
        ),
        sa.Column("third_largest_property_use_type_gfa", sa.Double(), nullable=True),
        sa.Column("has_natural_gas", sa.Boolean(), nullable=False),
        sa.Column("has_steam", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=32), nullable=True),
        sa.Column("prep_version", sa.String(length=32), nullable=False),
        _created_at("prepared_at"),
        sa.CheckConstraint(
            "data_year BETWEEN 2015 AND 2100",
            name=op.f("ck_building_years_data_year_range"),
        ),
        sa.CheckConstraint(
            "exclusion_reason IN ('outlier', 'non_compliant', "
            "'non_positive_target', 'missing_target', "
            "'aberrant_energy', 'aberrant_emissions')",
            name=op.f("ck_building_years_exclusion_reason_values"),
        ),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["buildings.id"],
            name=op.f("fk_building_years_building_id_buildings"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_building_years")),
        sa.UniqueConstraint(
            "building_id", "data_year", name=op.f("uq_building_years_building_id")
        ),
    )
    op.create_index(
        "ix_building_years_data_year", "building_years", ["data_year"], unique=False
    )
    op.create_table(
        "building_actuals",
        sa.Column("building_year_id", sa.BigInteger(), nullable=False),
        sa.Column("site_energy_use_kbtu", sa.Double(), nullable=True),
        sa.Column("total_ghg_emissions_tco2e", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["building_year_id"],
            ["building_years.id"],
            name=op.f("fk_building_actuals_building_year_id_building_years"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("building_year_id", name=op.f("pk_building_actuals")),
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("api_request_id", sa.BigInteger(), nullable=True),
        sa.Column("building_year_id", sa.BigInteger(), nullable=True),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "input_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("energy_use_kbtu", sa.Double(), nullable=False),
        sa.Column("ghg_emissions_tco2e", sa.Double(), nullable=False),
        _created_at("predicted_at"),
        sa.CheckConstraint(
            "api_request_id IS NOT NULL OR building_year_id IS NOT NULL",
            name=op.f("ck_predictions_has_origin"),
        ),
        sa.ForeignKeyConstraint(
            ["api_request_id"],
            ["api_requests.id"],
            name=op.f("fk_predictions_api_request_id_api_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["building_year_id"],
            ["building_years.id"],
            name=op.f("fk_predictions_building_year_id_building_years"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ml_models.id"],
            name=op.f("fk_predictions_model_id_ml_models"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
    )
    op.create_index(
        "ix_predictions_model_predicted",
        "predictions",
        ["model_id", "predicted_at"],
        unique=False,
    )
    op.create_index(
        "ix_predictions_api_request_id", "predictions", ["api_request_id"], unique=False
    )
    op.create_index(
        "ix_predictions_building_year_id",
        "predictions",
        ["building_year_id"],
        unique=False,
    )
    op.create_index(
        "uq_predictions_batch",
        "predictions",
        ["building_year_id", "model_id"],
        unique=True,
        postgresql_where=sa.text("api_request_id IS NULL"),
    )
    op.execute(PROJECTED_EVALUATION_VIEW)


def downgrade() -> None:
    raise NotImplementedError(
        "Migration destructive : restaurer une sauvegarde (ou repartir de "
        "`create_db` et `ingest`) plutôt que de redescendre."
    )
