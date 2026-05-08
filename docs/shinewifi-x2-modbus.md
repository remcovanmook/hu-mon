This document provides the full technical specification for interacting with the **2025-2026 Growatt 3-Phase Hybrid Generation** (MOD-HU, MOD-XH, MID-XH series) via the **ShineWifi-X2** datalogger.

---

# Growatt 3-Phase Hybrid (Protocol II) Specification
**Interface:** Modbus TCP via ShineWifi-X2  
**Protocol Version:** Growatt Modbus RTU Protocol II (Storage/Hybrid v7.6+)  
**Port:** `502`

## 1. Connection Parameters
| Parameter | Value | Notes |
| :--- | :--- | :--- |
| **Transport** | TCP/IP | Local Network |
| **Port** | `502` | Specific to X2 series local Modbus |
| **Slave ID** | `1` | Default (Adjustable in Inverter LCD settings) |
| **Byte Order** | Big-Endian | High Byte first, then Low Byte |
| **Register Order** | Big-Endian | High Register first (for 32-bit values) |
| **Timeout** | `2.0s - 5.0s` | ShineWifi-X2 hardware is low-power |

---

## 2. Data Types & Representation
* **$U16$**: 16-bit Unsigned Integer (1 register).
* **$S16$**: 16-bit Signed Integer (1 register, two's complement).
* **$U32$**: 32-bit Unsigned Integer (2 registers). Value = $(Reg_{High} \times 65536) + Reg_{Low}$.
* **$S32$**: 32-bit Signed Integer (2 registers, two's complement). Used for Grid and Battery power.
* **Scaling**: Most values are scaled by $10$ ($0.1$) or $100$ ($0.01$). If a register value is $2305$ with a $0.1$ scale, the actual value is $230.5$.

---

## 3. Firmware Architecture & Compatibility
Based on the "Shifted Contiguous" logic and the firmware branches (e.g. `7.6.x`), this mapping applies across the modern Growatt 3-Phase ecosystem. Growatt reuses the same DSP code across chassis families:

* **Direct Coverage:** The entire `MOD-HU` (3kW-15kW) and `MOD-XH` series. These share the exact internal architecture and Modbus mapping.
* **High Likelihood (Close Cousins):** The `MID-XH` (11kW-30kW) commercial versions and the latest `SPH TL3-BH-UP` hybrids. They utilize the same Protocol II stack and 3-phase telemetry structures.
* **Partial Overlap:** The single-phase `MIN-XH` series will lack the 3-phase Grid and EPS blocks, but likely shares the Metadata (`3001`) and Thermal (`3094`) shifts.

### The "North Star" Auto-Detection Heuristic
Because legacy single-phase mappings and older Protocol I maps clash with this contiguous block architecture, software should use an auto-detection heuristic before parsing this map. 

If you read `Reg 3025` and it returns the Grid Frequency (e.g., `>4000` for 50Hz) and `Reg 3026` returns a valid L1 Voltage (e.g., `>1000`), you have a positive lock on the **Shifted-Contiguous Unit** profile, regardless of the model string.

---

## 4. Firmware Memory Layout Patterns
Growatt's three-phase firmware relies on three strictly consistent data structures to pack memory:

### A. The "4-Register Power Block" (Used for PV and Grid)
For direct energy sources, exactly 4 registers are allocated per channel in the sequence: `Voltage (U16)`, `Current (U16)`, `Power High (U16)`, `Power Low (U16)`.
* **PV Strings (`3003` to `3018`)**:
  * `3003-3006`: PV1 V, PV1 A, PV1 Power (U32)
  * `3007-3010`: PV2 V, PV2 A, PV2 Power (U32)
* **Grid Channels (`3026` to `3037`)**:
  * `3026-3029`: L1 V, L1 A, L1 Power (U32)
  * `3030-3033`: L2 V, L2 A, L2 Power (U32)

### B. The "Split Phase Block" (Used for EPS and Smart Meter)
For internal load calculations, the firmware does not interleave Voltage/Current with Power. It lists all V/A pairs sequentially, followed by a contiguous block of U32 Powers.
* **EPS Block (`3130` to `3141`)**:
  * `3130-3135`: L1 V/A, L2 V/A, L3 V/A (6 contiguous registers)
  * `3136-3141`: L1 Power, L2 Power, L3 Power (6 contiguous registers, U32 format)
* **Smart Meter Block (`3121` to `3128`)**:
  * The smart meter doesn't report voltage to the inverter, so it just lists the powers directly: Total Net, L1 Net, L2 Net, L3 Net.

### C. The "Today/Total Counters" (Used for Energy)
Every lifetime energy metric is allocated exactly 4 contiguous registers: `Today (U32)` followed immediately by `Total (U32)`.
* `3049-3052`: PV Today / PV Total
* `3176-3179`: Bat Discharge Today / Discharge Total
* `3184-3187`: Grid Import Today / Import Total
* `3188-3191`: Load Today / Load Total

---

## 5. Consolidated Register Map (Function Code 04)
These registers are Read-Only and provide real-time telemetry.

| Function Code | Address | Name | Type | Unit | Scale | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **METADATA** | *(Read Once)* | | | | | |
| 03 (Hold) | 9–14 | Firmware Ver | U16×6 | — | — | System Firmware versions |
| 03 (Hold) | 28–29 | Module ID | U32 | — | — | Algorithmic Series + Power ID |
| 03 (Hold) | 121 | Device Type | U16 | — | — | 6: Storage/Hybrid |
| 03 (Hold) | 3001-15 | New Serial | ASCII | — | — | 30-char Inverter Serial Number |
| **SYSTEM STATE** | | | | | | |
| 04 (Input) | 3000 | Inverter Status | U16 | — | 1 | 0:Wait, 1:Normal, 3:Fault |
| 04 (Input) | 3105 | Fault Code | U16 | — | 1 | Main Error code (0 = None) |
| 04 (Input) | 3106 | Warning Code | U16 | — | 1 | Warning bitmask |
| 04 (Input) | 3094 | Inverter Temp | U16 | °C | 0.1 | Heat sink temperature (HU-Hybrid -20 Shift Profile) |
| 04 (Input) | 3095 | Boost Temp | U16 | °C | 0.1 | Internal converter temperature (HU-Hybrid -20 Shift Profile) |
| **PV INPUTS** | | | | | | |
| 04 (Input) | 3001-02 | Total PV Power | U32 | W | 0.1 | Combined solar input |
| 04 (Input) | 3003-04 | PV1 V / I | U16×2 | V/A | 0.1 | String 1 Voltage & Amps |
| 04 (Input) | 3005-06 | PV1 Power | U32 | W | 0.1 | String 1 Watts |
| 04 (Input) | 3007-08 | PV2 V / I | U16×2 | V/A | 0.1 | String 2 Voltage & Amps |
| 04 (Input) | 3009-10 | PV2 Power | U32 | W | 0.1 | String 2 Watts |
| 04 (Input) | 3011-12 | PV3 V / I | U16×2 | V/A | 0.1 | String 3 Voltage & Amps |
| 04 (Input) | 3013-14 | PV3 Power | U32 | W | 0.1 | String 3 Watts |
| 04 (Input) | 3015-16 | PV4 V / I | U16×2 | V/A | 0.1 | String 4 Voltage & Amps |
| 04 (Input) | 3017-18 | PV4 Power | U32 | W | 0.1 | String 4 Watts |
| **GRID & METER** | | | | | | |
| 04 (Input) | 3030-31 | Grid L1 V / I | U16×2 | V/A | 0.1 | Grid Phase 1 status |
| 04 (Input) | 3034-35 | Grid L2 V / I | U16×2 | V/A | 0.1 | Grid Phase 2 status |
| 04 (Input) | 3038-39 | Grid L3 V / I | U16×2 | V/A | 0.1 | Grid Phase 3 status (Standard Profile) |
| 04 (Input) | 3025 | Grid Freq | U16 | Hz | 0.01 | Displaced Grid Frequency (HU-Hybrid Profile) |
| 04 (Input) | 3026-27 | Grid L1 V / I | U16×2 | V/A | 0.1 | Displaced Grid Phase 1 (HU-Hybrid Profile) |
| 04 (Input) | 3028-29 | Grid L1 Power | U32 | W | 0.1 | Displaced Phase 1 Active Power |
| 04 (Input) | 3030-31 | Grid L2 V / I | U16×2 | V/A | 0.1 | Displaced Grid Phase 2 (HU-Hybrid Profile) |
| 04 (Input) | 3032-33 | Grid L2 Power | U32 | W | 0.1 | Displaced Phase 2 Active Power |
| 04 (Input) | 3034-35 | Grid L3 V / I | U16×2 | V/A | 0.1 | Displaced Grid Phase 3 (HU-Hybrid Profile) |
| 04 (Input) | 3036-37 | Grid L3 Power | U32 | W | 0.1 | Displaced Phase 3 Active Power |
| 04 (Input) | 3038-40 | Grid L-L V | U16×3 | V | 0.1 | V_RS, V_ST, V_TR Delta (HU-Hybrid Profile) |
| 04 (Input) | 3121-22 | Total Meter P | S32 | W | 0.1 | Net (+ Export, - Import) |
| 04 (Input) | 3123-24 | Meter L1 P | S32 | W | 0.1 | Phase 1 Net Power |
| 04 (Input) | 3125-26 | Meter L2 P | S32 | W | 0.1 | Phase 2 Net Power |
| 04 (Input) | 3127-28 | Meter L3 P | S32 | W | 0.1 | Phase 3 Net Power |
| **EPS (BACKUP)** | | | | | | |
| 04 (Input) | 3130 | EPS V L1 | U16 | V | 0.1 | Backup Voltage Phase 1 |
| 04 (Input) | 3131 | EPS I L1 | U16 | A | 0.1 | Backup Current Phase 1 |
| 04 (Input) | 3132 | EPS V L2 | U16 | V | 0.1 | Backup Voltage Phase 2 |
| 04 (Input) | 3133 | EPS I L2 | U16 | A | 0.1 | Backup Current Phase 2 |
| 04 (Input) | 3134 | EPS V L3 | U16 | V | 0.1 | Backup Voltage Phase 3 |
| 04 (Input) | 3135 | EPS I L3 | U16 | A | 0.1 | Backup Current Phase 3 |
| 04 (Input) | 3136-37 | EPS L1 P | U32 | W | 0.1 | Phase 1 Backup Watts |
| 04 (Input) | 3138-39 | EPS L2 P | U32 | W | 0.1 | Phase 2 Backup Watts |
| 04 (Input) | 3140-41 | EPS L3 P | U32 | W | 0.1 | Phase 3 Backup Watts |
| **BATTERY APX (HOLDING REGISTERS)** | | | | | | |
| 03 (Hold) | 1001 | Battery Type | U16 | — | 1 | 1: Lithium (APX) |
| 03 (Hold) | 1002 | Design Capacity | U16 | Ah | 1 | Nominal capacity in Amp-hours |
| 03 (Hold) | 1005 | Nominal Energy | U16 | kWh | 0.1 | Total energy (e.g., 50 = 5.0kWh) |
| 03 (Hold) | 3037 | Max Charge Power | U16 | W | 1 | Maximum watts the APX can take |
| 03 (Hold) | 3038 | Max Discharge Power | U16 | W | 1 | Maximum discharge watts |
| **BATTERY APX (BMS & BDC HEALTH)** | | | | | | |
| 04 (Input) | 1013 | Battery SOH | U16 | % | 1 | State of Health (0-100) |
| 04 (Input) | 1017 | Cycle Count | U16 | — | 1 | Lifetime battery cycles |
| 04 (Input) | 3170 | Master SOC | U16 | % | 1 | Aggregated State of Charge |
| 04 (Input) | 3171 | Battery V | U16 | V | 0.1 | Total DC Bus Voltage |
| 04 (Input) | 3172 | Battery I | S16 | A | 0.1 | (+ Charge, - Discharge) |
| 04 (Input) | 3173-74 | Battery P | S32 | W | 0.1 | (+ Charge, - Discharge) |
| 04 (Input) | 3175 | BMS Temperature | U16 | °C | 0.1 | Internal controller temp |
| **APX MODULES (MODULE-LEVEL DEEP DIVE)** | | | | | | |
| 04 (Input) | 5400 / 5500 | Mod 1/2 SOC | U16 | % | 1 | SOC of the 5kWh brick |
| 04 (Input) | 5401 / 5501 | Mod 1/2 Voltage | U16 | V | 0.1 | Actual voltage of that brick |
| 04 (Input) | 5402 / 5502 | Mod 1/2 Current | S16 | A | 0.1 | Amps through that brick |
| 04 (Input) | 5403 / 5503 | Max Cell Temp | U16 | °C | 0.1 | Hottest cell in module |
| 04 (Input) | 5404 / 5504 | Min Cell Temp | U16 | °C | 0.1 | Coldest cell in module |
| 04 (Input) | 5407 / 5507 | Module SOH | U16 | % | 1 | State of Health per brick |
| **ENERGY TOTALS** | | | | | | || **ENERGY TOTALS** | | | | | | |
| 04 (Input) | 3049-50 | Epv Today | U32 | kWh | 0.1 | Solar generated today |
| 04 (Input) | 3053-54 | Eac Today | U32 | kWh | 0.1 | System AC energy today |
| 04 (Input) | 3051-52 | Epv Total | U32 | kWh | 0.1 | Solar lifetime |
| 04 (Input) | 3055-56 | Eac Total | U32 | kWh | 0.1 | System AC energy lifetime |
| 04 (Input) | 3176-77 | Disch. Today | U32 | kWh | 0.1 | Battery energy out today |
| 04 (Input) | 3180-81 | Charge Today | U32 | kWh | 0.1 | Battery energy in today |
| 04 (Input) | 3184-85 | Import Today | U32 | kWh | 0.1 | Bought from Grid today |
| 04 (Input) | 3186-87 | Export Today | U32 | kWh | 0.1 | Sold to Grid today |
| 04 (Input) | 3188-89 | Load Today | U32 | kWh | 0.1 | House used today |
| 04 (Input) | 3190-91 | Import Total | U32 | kWh | 0.1 | Lifetime bought from Grid |
| 04 (Input) | 3192-93 | Export Total | U32 | kWh | 0.1 | Lifetime sold to Grid |
| 04 (Input) | 3194-95 | Load Total | U32 | kWh | 0.1 | Lifetime house usage |

### Power Quality & Unmapped (3155-3169)
| 04 (Input) | 3161 | Total Power Factor | U16 | — | 10000 | 10000 = 1.0 PF |
| 04 (Input) | 3162-64 | Phase L1/L2/L3 PF | U16 | — | 10000 | Power factor per phase |


---


## 6. Device Identification & Status
### Algorithmic Model Decoding (Holding Reg 28-29)
The inverter's exact model name and power rating are not stored as ASCII. Instead, they are algorithmically encoded in a 32-bit integer spread across Holding Registers `28` and `29` (Function Code 03):
1. Compute `module_id = (Reg[28] << 16) | Reg[29]`
2. Extract the Series Code (Upper 16 bits): `series_code = (module_id >> 16) & 0xFFFF`
3. Extract the Power Rating (Lower 16 bits): `power_watts = module_id & 0xFFFF`

**Known Series Codes & Phase Mappings:**
* `0x05`: **MIN** (Single-Phase)
* `0x0B`: **MOD** (Three-Phase)
* `0x0C`: **MID** (Three-Phase)
* `0x0D`: **SPH** (Single/Three-Phase Hybrid)
* `0x0E`: **SPA** (AC Coupled)
* `0x0F`: **MIC** (Single-Phase)
* `0x10`: **MAC** (Three-Phase)
* `0x11`: **MAX** (Three-Phase)

#### Deriving the Full Model String
The base registers only provide `MOD` and `12000`. The rest of the string (`KTL3-HU`) is constructed via the following logic:
1. **`K` (Kilo):** If `power_watts` $\ge 3000$, it is divided by $1000$ and appended with `K` (e.g., `12000` $\rightarrow$ `12K`).
2. **`TL` (Transformer-Less):** Assumed universally for all modern Growatt grid-tied architectures.
3. **`3` (Three-Phase):** Explicitly appended if the Series is natively 3-phase (like `MOD`, `MID`, `MAX`).
4. **`-HU` / `-XH` (Feature Suffix):** 
   * Suffixes are explicitly derived from the **Device Type** flag located at **Holding Register 121**.
   * If `Reg[121] == 6`: Full Hybrid (High-Voltage APX). Appends `-HU`.
   * If `Reg[121] == 4`: Battery-Ready (No EPS). Appends `-XH`.

*(Example: `module_id` yields `MOD` and `12000`. It is $\ge 3000$, so it becomes `12K`. `MOD` is natively 3-phase, adding `TL3`. `Reg[121]` returns `6` (Storage/Hybrid), appending `-HU`. Final result: `MOD 12KTL3-HU`.)*

### Inverter Status (Input Reg 3000)
* **0**: Waiting (Startup or low light)
* **1**: Normal (Generating or Battery active)
* **3**: Fault (Red LED active, system halted)
* **4**: Flash (Firmware updating)

### Fault Codes (Input Reg 3105)
* **201**: Leakage current too high
* **202**: DC Isolation error
* **300**: Grid AC voltage out of range
* **302**: Grid frequency out of range

---

## 7. Interaction Sequence (Polling Strategy)
Due to the memory constraints of the ESP32 in the ShineWifi-X2, the following interaction sequence is required for stability:

1.  **Open Connection**: Establish Modbus TCP on 5020.
2.  **Poll Segment 1 (PV/Status)**: Read `3000` for 25 registers.
3.  **Short Wait**: Delay `50ms - 100ms`.
4.  **Poll Segment 2 (Grid/Load)**: Read `3030` for 30 registers.
5.  **Short Wait**: Delay `50ms - 100ms`.
6.  **Poll Segment 3 (Battery)**: Read `3170` for 15 registers.
7.  **Calculate & Store**:
    * Assemble 32-bit values.
    * Coerce any floating PV values ($6553.5V$) to $0$.
    * Apply scaling.
8.  **Close or Idle**: Either close the socket or wait `5 seconds` before the next cycle.

## 8. Known Constraints
* **Max Register Read**: Do not exceed **64 registers** per single Modbus request.
* **Concurrent Connections**: The ShineWifi-X2 generally supports only **one** concurrent TCP connection on 502. If multiple clients connect, the datalogger often reboots.
* **Night Mode**: When PV voltage is zero, some registers may hold their "Last Known Good" value or revert to `0xFFFF` ($65535$). The API must filter these.