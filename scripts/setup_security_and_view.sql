-- 1. Schema for the clean views the AI agent is allowed to read
CREATE SCHEMA IF NOT EXISTS fde_views;

-- 2. Semantic view: translate legacy column names into plain English
CREATE OR REPLACE VIEW fde_views.vw_active_fleet AS
SELECT
    evt_dttm_utc    AS event_timestamp_utc,
    gps_lat_deg     AS latitude,
    gps_lng_deg     AS longitude,
    snsr_tmp_c      AS cargo_temperature_c,
    crg_stat_ind    AS cargo_condition_status,
    rsk_cat_desc    AS risk_classification,
    dly_prb_rt      AS delay_probability,
    rte_hzrd_lvl    AS route_risk_level,
    port_cong_scr   AS port_congestion_level,
    trf_cong_lvl    AS traffic_congestion_level,
    wx_sev_idx      AS weather_severity,
    eta_var_hrs     AS eta_variation_hours,
    fuel_burn_rt    AS fuel_consumption_rate,
    drv_bhv_scr     AS driver_behavior_score,
    drv_ftg_scr     AS driver_fatigue_score,
    cstm_clr_tm     AS customs_clearance_time,
    dsrpt_lkl_scr   AS disruption_likelihood_score,
    dlv_tm_dev      AS delivery_time_deviation,
    whs_inv_lvl     AS warehouse_inventory_level,
    ld_unld_tm      AS loading_unloading_time,
    hndl_eqp_avl    AS handling_equipment_availability,
    ord_ffl_stat    AS order_fulfillment_status,
    shp_cst_amt     AS shipping_cost,
    sup_rlb_scr     AS supplier_reliability_score,
    lead_tm_dys     AS lead_time_days,
    hist_dmd_qty    AS historical_demand
FROM legacy.t_rfr_tlm_hist;

-- 3. Read-only login for the AI agent
CREATE ROLE usr_fde_ro LOGIN PASSWORD 'AgentPassword2026';

-- 4. Grant access ONLY to the clean view
GRANT CONNECT ON DATABASE cold_chain TO usr_fde_ro;
GRANT USAGE ON SCHEMA fde_views TO usr_fde_ro;
GRANT SELECT ON fde_views.vw_active_fleet TO usr_fde_ro;

-- 5. Lock everything else down (Postgres has no DENY: anything not granted is denied)
REVOKE ALL ON SCHEMA legacy FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
