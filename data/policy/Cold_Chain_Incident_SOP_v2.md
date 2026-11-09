# Southern California Logistics Operations
## Standard Operating Procedure (SOP): Cold-Chain & Transit Anomalies
**Version:** 2.4 | **Effective Date:** Jan 2021 | **Confidentiality:** Internal Operations Only

### 1. Temperature Control & Spoilage Prevention (Cold-Chain)
All refrigerated fleets must maintain strict IoT temperature compliance to prevent cargo spoilage.
* **Fresh Perishables:** IoT temperature must remain between 0.0°C and 4.0°C. 
* **Critical Breach:** If `cargo_temperature_c` exceeds **4.0°C**, an immediate cold-chain breach is declared. 
* **Mitigation Protocol:** The dispatcher must immediately contact the driver to restart the auxiliary cooling unit. If `eta_variation_hours` is greater than **1**, divert the vehicle to the nearest emergency cold-storage facility.

### 2. Route Congestion & Diversion Tactics
Port congestion heavily impacts SLA compliance. 
* **Port of Long Beach / LA:** If `port_congestion_level` exceeds a severity index of **7.0**, standard routing is suspended.
* **Mitigation Protocol:** Do not hold freight at the port. Divert all active shipments to the **Inland Empire Overflow Depot (San Bernardino)** for cross-docking.

### 3. Risk Classification Triggers
Any shipment classified as **"High Risk"** (`risk_classification` = High Risk) combined with a `delay_probability` greater than **0.65** must be escalated to the Tier 2 Logistics Manager.