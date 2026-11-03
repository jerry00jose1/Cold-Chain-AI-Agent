import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text

project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

data_path = project_root / "data" / "raw" / "dynamic_supply_chain_logistics_dataset.csv"

LEGACY_SCHEMA = "legacy"
LEGACY_TABLE = "t_rfr_tlm_hist"

# Legacy reefer (refrigerated truck) telemetry naming, as found in an old TMS
legacy_mapping = {
    "timestamp": "evt_dttm_utc",
    "vehicle_gps_latitude": "gps_lat_deg",
    "vehicle_gps_longitude": "gps_lng_deg",
    "iot_temperature": "snsr_tmp_c",
    "cargo_condition_status": "crg_stat_ind",
    "risk_classification": "rsk_cat_desc",
    "delay_probability": "dly_prb_rt",
    "route_risk_level": "rte_hzrd_lvl",
    "port_congestion_level": "port_cong_scr",
    "traffic_congestion_level": "trf_cong_lvl",
    "weather_condition_severity": "wx_sev_idx",
    "eta_variation_hours": "eta_var_hrs",
    "fuel_consumption_rate": "fuel_burn_rt",
    "driver_behavior_score": "drv_bhv_scr",
    "fatigue_monitoring_score": "drv_ftg_scr",
    "customs_clearance_time": "cstm_clr_tm",
    "disruption_likelihood_score": "dsrpt_lkl_scr",
    "delivery_time_deviation": "dlv_tm_dev",
    "warehouse_inventory_level": "whs_inv_lvl",
    "loading_unloading_time": "ld_unld_tm",
    "handling_equipment_availability": "hndl_eqp_avl",
    "order_fulfillment_status": "ord_ffl_stat",
    "shipping_costs": "shp_cst_amt",
    "supplier_reliability_score": "sup_rlb_scr",
    "lead_time_days": "lead_tm_dys",
    "historical_demand": "hist_dmd_qty",
}

engine = create_engine(
    URL.create(
        "postgresql+psycopg",
        username=os.getenv("PG_ADMIN_USER"),
        password=os.getenv("PG_ADMIN_PASSWORD"),
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DB"),
    )
)

print(f"Loading CSV from {data_path}...")
df = pd.read_csv(data_path, parse_dates=["timestamp"])

df_legacy = df[list(legacy_mapping.keys())].rename(columns=legacy_mapping)
df_legacy["src_sys_cd"] = "TMS01"
df_legacy["ld_dttm_utc"] = datetime.now(timezone.utc)

print(f"Connecting to Postgres database '{os.getenv('PG_DB')}'...")
with engine.begin() as conn:
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {LEGACY_SCHEMA}"))

print(f"Ingesting {len(df_legacy)} rows into {LEGACY_SCHEMA}.{LEGACY_TABLE}...")
df_legacy.to_sql(
    LEGACY_TABLE,
    engine,
    schema=LEGACY_SCHEMA,
    if_exists="replace",
    index=False,
    chunksize=1000,
    method="multi",
)

with engine.connect() as conn:
    row_count = conn.execute(
        text(f"SELECT COUNT(*) FROM {LEGACY_SCHEMA}.{LEGACY_TABLE}")
    ).scalar()

print(f"Legacy data ingestion complete: {row_count} rows in {LEGACY_SCHEMA}.{LEGACY_TABLE}")
