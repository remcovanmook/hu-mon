This document provides the full technical specification for interacting with the **Growatt MOD 12KTL3-HU** hybrid inverter via the **ShineWifi-X2** datalogger.

---

# Growatt 12KTL3-HU Interaction Specification
**Interface:** Modbus TCP via ShineWifi-X2  
**Protocol Version:** Growatt Modbus RTU Protocol II (Storage/Hybrid)  
**Port:** `5020`

## 1. Connection Parameters
| Parameter | Value | Notes |
| :--- | :--- | :--- |
| **Transport** | TCP/IP | Local Network |
| **Port** | `5020` | Specific to X2 series local Modbus |
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

## 3. Input Register Map (Function Code 04)
These registers are Read-Only and provide real-time telemetry.

### 3.1. System Status & PV Input (MPPT 1-4)
| Address | Name | Type | Unit | Scale | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **3000** | Inverter Status | $U16$ | — | 1 | 0:Wait, 1:Normal, 3:Fault |
| **3001-2** | P_PV_Total | $U32$ | $W$ | 0.1 | Combined input power |
| **3003** | PV1_Voltage | $U16$ | $V$ | 0.1 | String 1 Voltage |
| **3004** | PV1_Current | $U16$ | $A$ | 0.1 | String 1 Current |
| **3005-6** | PV1_Power | $U32$ | $W$ | 0.1 | String 1 Watts |
| **3007** | PV2_Voltage | $U16$ | $V$ | 0.1 | String 2 Voltage |
| **3008** | PV2_Current | $U16$ | $A$ | 0.1 | String 2 Current |
| **3009-10**| PV2_Power | $U32$ | $W$ | 0.1 | String 2 Watts |
| **3011** | PV3_Voltage | $U16$ | $V$ | 0.1 | String 3 Voltage |
| **3012** | PV3_Current | $U16$ | $A$ | 0.1 | String 3 Current |
| **3013-14**| PV3_Power | $U32$ | $W$ | 0.1 | String 3 Watts |
| **3015** | PV4_Voltage | $U16$ | $V$ | 0.1 | String 4 Voltage |
| **3016** | PV4_Current | $U16$ | $A$ | 0.1 | String 4 Current |
| **3017-18**| PV4_Power | $U32$ | $W$ | 0.1 | String 4 Watts |

### 3.2. Grid & Meter (3-Phase)
| Address | Name | Type | Unit | Scale | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **3030** | V_Grid_L1 | $U16$ | $V$ | 0.1 | Phase 1 Voltage |
| **3031** | I_Grid_L1 | $U16$ | $A$ | 0.1 | Phase 1 Current |
| **3034** | V_Grid_L2 | $U16$ | $V$ | 0.1 | Phase 2 Voltage |
| **3035** | I_Grid_L2 | $U16$ | $A$ | 0.1 | Phase 2 Current |
| **3038** | V_Grid_L3 | $U16$ | $V$ | 0.1 | Phase 3 Voltage |
| **3039** | I_Grid_L3 | $U16$ | $A$ | 0.1 | Phase 3 Current |
| **3042** | Frequency | $U16$ | $Hz$ | 0.01 | Grid Frequency |
| **3121-2** | P_Meter_Total| $S32$ | $W$ | 0.1 | **Pos: Export, Neg: Import** |

### 3.3. Battery & Load
| Address | Name | Type | Unit | Scale | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **3170** | Battery_SOC | $U16$ | $\%$ | 1 | State of Charge (0-100) |
| **3171** | Battery_V | $U16$ | $V$ | 0.1 | High Voltage Bus |
| **3172** | Battery_I | $S16$ | $A$ | 0.1 | Pos: Charge, Neg: Discharge |
| **3173-4** | Battery_P | $S32$ | $W$ | 0.1 | Pos: Charge, Neg: Discharge |
| **3048-9** | Load_P | $U32$ | $W$ | 0.1 | Total House Load |
| **3120** | EPS_P | $U32$ | $W$ | 0.1 | Power on Backup Port |

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