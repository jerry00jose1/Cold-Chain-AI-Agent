import json
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pandas as pd
from langchain_core.tools import tool
from langchain_pinecone import PineconeVectorStore
from sqlalchemy import text

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.settings import database_engine, embedding_index, get_embeddings

VIEW_NAME = "fde_views.vw_active_fleet"
MAX_ROWS = 25

_engine = None
_retriever = None


def get_agent_engine():
    global _engine
    if _engine is None:
        _engine = database_engine(
            os.getenv("PG_AGENT_USER", ""),
            os.getenv("PG_AGENT_PASSWORD", ""),
        )
    return _engine


def get_retriever():
    global _retriever
    if _retriever is None:
        index_name, _dimension = embedding_index()
        vector_store = PineconeVectorStore(index_name=index_name, embedding=get_embeddings())
        _retriever = vector_store.as_retriever(search_kwargs={"k": 2})
    return _retriever


def _single_select(sql_query: str) -> str:
    statement = sql_query.strip().rstrip(";").strip()
    if not statement:
        raise ValueError("Query is empty.")
    if ";" in statement:
        raise ValueError("Only one SELECT statement is allowed.")
    if not statement.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed.")
    return statement


@tool
def query_telemetry_db(sql_query: str) -> str:
    """Query refrigerated-fleet telemetry in PostgreSQL.

    Run one SELECT against fde_views.vw_active_fleet only.
    Columns: event_timestamp_utc, latitude, longitude, cargo_temperature_c,
    cargo_condition_status, risk_classification, delay_probability,
    route_risk_level, port_congestion_level, traffic_congestion_level,
    weather_severity, eta_variation_hours, fuel_consumption_rate,
    driver_behavior_score, driver_fatigue_score, customs_clearance_time,
    disruption_likelihood_score, delivery_time_deviation,
    warehouse_inventory_level, loading_unloading_time,
    handling_equipment_availability, order_fulfillment_status, shipping_cost,
    supplier_reliability_score, lead_time_days, historical_demand.

    Write PostgreSQL, not T-SQL: use LIMIT, not TOP. Readings run from
    2021-01-01 through 2024-08-29, so filter event_timestamp_utc inside that
    range. At most 25 rows are returned.
    """
    try:
        statement = _single_select(sql_query)
        wrapped = text(f"SELECT * FROM ({statement}) AS agent_query LIMIT {MAX_ROWS}")
        with get_agent_engine().connect() as conn:
            conn.execute(text("SET LOCAL statement_timeout = '15s'"))
            frame = pd.read_sql(wrapped, conn)
    except Exception as exc:
        return f"Database Error: {exc}"

    if frame.empty:
        return "Query returned no rows."
    return frame.to_string(index=False)


@tool
def fetch_corridor_conditions(latitude: float, longitude: float) -> str:
    """Fetch live weather for a GPS point from Open-Meteo.

    Returns outside air temperature, wind speed, and a corridor congestion
    index derived from wind. This is external weather, not the database
    columns weather_severity or port_congestion_level.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}&current_weather=true"
    )
    try:
        with urlopen(url, timeout=6) as response:
            payload = json.load(response).get("current_weather", {})
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return f"Corridor API Communication Failure: {exc}"

    wind = float(payload.get("windspeed") or 0.0)
    temperature = payload.get("temperature", "N/A")
    congestion_index = 8.5 if wind > 10.0 else 2.5
    status_note = "High Transit Disruption" if wind > 10.0 else "Corridor Normal"
    return (
        "--- LIVE CORRIDOR TELEMETRY ---\n"
        f"Target GPS: {latitude}, {longitude}\n"
        f"External Temp: {temperature}°C | Wind Speed: {wind} km/h\n"
        f"Corridor Risk: {status_note} (Congestion Index: {congestion_index}/10)\n"
        "-------------------------------"
    )


@tool
def search_compliance_sop(query: str) -> str:
    """Search the cold-chain SOP stored in Pinecone.

    Use this for temperature limits, breach actions, port-diversion rules,
    and escalation thresholds. Cite the returned source file.
    """
    try:
        matched_docs = get_retriever().invoke(query)
    except Exception as exc:
        return f"Vector Store Retrieval Error: {exc}"

    if not matched_docs:
        return "No matching compliance clauses found."

    formatted = "\n\n".join(
        f"[Source: {doc.metadata.get('source_file', 'SOP')}]\n{doc.page_content}"
        for doc in matched_docs
    )
    return f"--- COMPLIANCE SOP CONTEXT ---\n{formatted}\n------------------------------"


if __name__ == "__main__":
    print(query_telemetry_db.invoke(
        "SELECT event_timestamp_utc, latitude, longitude, cargo_temperature_c "
        f"FROM {VIEW_NAME} "
        "WHERE cargo_temperature_c > 4 "
        "ORDER BY event_timestamp_utc DESC "
        "LIMIT 2"
    ))
    print(fetch_corridor_conditions.invoke({"latitude": 33.77, "longitude": -118.19}))
    print(search_compliance_sop.invoke("What is the temperature limit for fresh perishables?"))
