This document provides the full technical specification for interacting with the **Growatt MOD 12KTL3-HU** hybrid inverter via the **ShineWifi-X2** datalogger.

---

# Growatt 12KTL3-HU Interaction Specification
**Interface:** Modbus TCP via ShineWifi-X2  
**Protocol Version:** Growatt Modbus RTU Protocol II (Storage/Hybrid)  
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

## 3. Consolidated Register Map (Function Code 04)
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
| 04 (Input) | 3091 | Fault Code | U16 | — | 1 | Main Error code (0 = None) |
| 04 (Input) | 3092 | Warning Code | U16 | — | 1 | Warning bitmask |
| 04 (Input) | 3114 | Inverter Temp | U16 | °C | 0.1 | Heat sink temperature |
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
| 04 (Input) | 3038-39 | Grid L3 V / I | U16×2 | V/A | 0.1 | Grid Phase 3 status |
| 04 (Input) | 3042 | Grid Freq | U16 | Hz | 0.01 | Grid Frequency |
| 04 (Input) | 3121-22 | Total Meter P | S32 | W | 0.1 | Net (+ Export, - Import) |
| 04 (Input) | 3123-24 | Meter L1 P | S32 | W | 0.1 | Phase 1 Net Power |
| 04 (Input) | 3125-26 | Meter L2 P | S32 | W | 0.1 | Phase 2 Net Power |
| 04 (Input) | 3127-28 | Meter L3 P | S32 | W | 0.1 | Phase 3 Net Power |
| **EPS (BACKUP)** | | | | | | |
| 04 (Input) | 3118 | EPS V L1 | U16 | V | 0.1 | Backup Voltage Phase 1 |
| 04 (Input) | 3130 | EPS V L2 | U16 | V | 0.1 | Backup Voltage Phase 2 |
| 04 (Input) | 3132 | EPS V L3 | U16 | V | 0.1 | Backup Voltage Phase 3 |
| 04 (Input) | 3120-21 | EPS Total P | U32 | W | 0.1 | Total Power on Backup port |
| 04 (Input) | 3136-37 | EPS L1 P | U32 | W | 0.1 | Phase 1 Backup Watts |
| 04 (Input) | 3138-39 | EPS L2 P | U32 | W | 0.1 | Phase 2 Backup Watts |
| 04 (Input) | 3140-41 | EPS L3 P | U32 | W | 0.1 | Phase 3 Backup Watts |
| 04 (Input) | 3131/33/35 | EPS I L1/2/3 | U16×3 | A | 0.1 | Current per Phase on EPS |
| **HOUSE LOAD** | | | | | | |
| 04 (Input) | N/A | House Total P | N/A | W | N/A | Derived mathematically (PV - Meter - Bat) |
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

---


## 4. Status and Error Decoding
### Inverter Status (Reg 3000)
* **0**: Waiting (Startup or low light)
* **1**: Normal (Generating or Battery active)
* **3**: Fault (Red LED active, system halted)
* **4**: Flash (Firmware updating)

### Fault Codes (Reg 3091)
* **201**: Leakage current too high
* **202**: DC Isolation error
* **300**: Grid AC voltage out of range
* **302**: Grid frequency out of range

---

## 5. Interaction Sequence (Polling Strategy)
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

## 6. Known Constraints
* **Max Register Read**: Do not exceed **64 registers** per single Modbus request.
* **Concurrent Connections**: The ShineWifi-X2 generally supports only **one** concurrent TCP connection on 5020. If multiple clients connect, the datalogger often reboots.
* **Night Mode**: When PV voltage is zero, some registers may hold their "Last Known Good" value or revert to `0xFFFF` ($65535$). The API must filter these.