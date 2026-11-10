import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.settings import database_engine

DATA_PATH = project_root / "data" / "raw" / "dynamic_supply_chain_logistics_dataset.csv"
LEGACY_SCHEMA = "legacy"
LEGACY_TABLE = "t_rfr_tlm_hist"

# Legacy reefer (refrigerated truck) telemetry naming, as found in an old TMS
LEGACY_MAPPING = {
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


def table_exists(conn) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :table
                )
                """
            ),
            {"schema": LEGACY_SCHEMA, "table": LEGACY_TABLE},
        ).scalar()
    )


def load_legacy_table(engine, frame: pd.DataFrame) -> int:
    """Reload rows without dropping the table, so views that depend on it stay valid."""
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {LEGACY_SCHEMA}"))
        exists = table_exists(conn)
        if exists:
            conn.execute(text(f"TRUNCATE TABLE {LEGACY_SCHEMA}.{LEGACY_TABLE}"))

    frame.to_sql(
        LEGACY_TABLE,
        engine,
        schema=LEGACY_SCHEMA,
        if_exists="append" if exists else "replace",
        index=False,
        chunksize=1000,
        method="multi",
    )
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {LEGACY_SCHEMA}.{LEGACY_TABLE}")).scalar()


def main() -> None:
    engine = database_engine(os.getenv("PG_ADMIN_USER", ""), os.getenv("PG_ADMIN_PASSWORD", ""))
    print(f"Loading CSV from {DATA_PATH}...")
    frame = pd.read_csv(DATA_PATH, parse_dates=["timestamp"])
    legacy = frame[list(LEGACY_MAPPING)].rename(columns=LEGACY_MAPPING)
    legacy["src_sys_cd"] = "TMS01"
    legacy["ld_dttm_utc"] = datetime.now(timezone.utc)

    print(f"Connecting to Postgres database '{os.getenv('PG_DB')}'...")
    print(f"Ingesting {len(legacy)} rows into {LEGACY_SCHEMA}.{LEGACY_TABLE}...")
    row_count = load_legacy_table(engine, legacy)
    print(f"Legacy data ingestion complete: {row_count} rows in {LEGACY_SCHEMA}.{LEGACY_TABLE}")


if __name__ == "__main__":
    main()
