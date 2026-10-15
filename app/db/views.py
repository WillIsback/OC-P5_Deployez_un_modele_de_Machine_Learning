"""Vues SQL (créées par la migration, pas par l'ORM)."""

PROJECTED_EVALUATION_VIEW = """
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
WHERE i.input_source = 'batch'
"""
