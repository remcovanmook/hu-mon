# Growatt Modbus TCP Reference

**Source:** VPP Communication Protocol V2.03 (GI-BK-E060), verified against MOD 12KTL3-HU (DTC 5401, firmware DO1.0ZBDC, VPP V2.02) via live probing.  
**Last updated:** 2026-05-09

---

## 1. Transport

| Parameter | Value |
|---|---|
| Interface | Modbus TCP (ShineWifi-X2 at port **502**, or local proxy at **5020**) |
| Slave ID | **1** (default; configurable via inverter LCD) |
| Byte order | Big-endian (high byte first) |
| Register order | Big-endian (high register first for 32-bit values) |
| Max registers per request | **125** (confirmed on ShineWifi-X2) |
| Concurrent connections | **1** — the ShineWifi-X2 TCP stack is single-threaded |
| Inter-request delay | **≥ 50 ms** between reads to avoid buffer overrun on ShineWifi |

The ShineWifi-X2 is a thin TCP→RS485 bridge. It does **not** have its own register space — every read goes through to the inverter over RS485.

---

## 2. Protocol Families

Growatt devices expose one or more register spaces depending on the product family.

| Protocol | Function Codes | Address Ranges | Who uses it |
|---|---|---|---|
| Protocol II (FC04 input) | FC04 | 3000–3374 | All modern grid-tie and hybrid |
| Protocol II (FC03 holding) | FC03 | 0–124, 3000–3374 | All modern |
| VPP holding | FC03 | 30000–30299 | MOD/MID-HU, MOD/MID-XH, MAX, WIT, WIS |
| VPP input | FC04 | 31000–31599 | Same as above |

### Device Detection (VPP)

On startup, probe FC04 3000–3029 to check if the inverter responds. If it does:

1. Read FC03 30000 — this is the **DTC code**.
2. Read FC03 30099 — this is the **VPP protocol version** (e.g. 202 = V2.02).
3. If 30099 is non-zero, the device supports VPP.

The DTC code determines the product family, phase count, and whether battery/EPS registers are present. See Section 5.

---

## 3. Data Types

| Type | Width | Notes |
|---|---|---|
| U16 | 1 register | Unsigned 16-bit |
| S16 | 1 register | Signed 16-bit, two's complement |
| U32 | 2 registers | High register first |
| S32 | 2 registers | Signed, high register first |
| ASCII | N registers | 2 chars per register, big-endian, null-padded |

---

## 4. Protocol II Register Map (FC04 Input, 3000–3374)

All registers read-only. Scale applies to the raw integer value.

### System State

| Address | Name | Type | Scale | Unit | Notes |
|---|---|---|---|---|---|
| 3000 | Inverter status | U16 | 1 | — | 0=Wait, 1=Normal, 3=Fault, 4=Flash |
| 3001–02 | Total PV power | U32 | 0.1 | W | |
| 3093 | Fault code | U16 | 1 | — | 0 = no fault |
| 3094 | Inverter temperature | U16 | 0.1 | °C | Heat sink |
| 3095 | Boost temperature | U16 | 0.1 | °C | Converter |

### PV Strings (4 strings per MPPT)

Each PV string occupies 4 registers: voltage, current, power H, power L.

| Address | Name | Type | Scale | Unit |
|---|---|---|---|---|
| 3003 | PV1 voltage | U16 | 0.1 | V |
| 3004 | PV1 current | U16 | 0.1 | A |
| 3005–06 | PV1 power | U32 | 0.1 | W |
| 3007 | PV2 voltage | U16 | 0.1 | V |
| 3008 | PV2 current | U16 | 0.1 | A |
| 3009–10 | PV2 power | U32 | 0.1 | W |
| 3011 | PV3 voltage | U16 | 0.1 | V |
| 3012 | PV3 current | U16 | 0.1 | A |
| 3013–14 | PV3 power | U32 | 0.1 | W |
| 3015 | PV4 voltage | U16 | 0.1 | V |
| 3016 | PV4 current | U16 | 0.1 | A |
| 3017–18 | PV4 power | U32 | 0.1 | W |

### Grid & Meter (3-phase)

| Address | Name | Type | Scale | Unit | Notes |
|---|---|---|---|---|---|
| 3025 | Grid frequency | U16 | 0.01 | Hz | |
| 3026 | Phase R voltage | U16 | 0.1 | V | L-N |
| 3027 | Phase R current | U16 | 0.1 | A | |
| 3028–29 | Phase R power | S32 | 0.1 | W | Signed (+ export) |
| 3030 | Phase S voltage | U16 | 0.1 | V | |
| 3031 | Phase S current | U16 | 0.1 | A | |
| 3032–33 | Phase S power | S32 | 0.1 | W | |
| 3034 | Phase T voltage | U16 | 0.1 | V | |
| 3035 | Phase T current | U16 | 0.1 | A | |
| 3036–37 | Phase T power | S32 | 0.1 | W | |
| 3038 | V_RS (line AB) | U16 | 0.1 | V | Line-to-line |
| 3039 | V_ST (line BC) | U16 | 0.1 | V | |
| 3040 | V_TR (line CA) | U16 | 0.1 | V | |

### EPS / Backup Output (3-phase, has_eps only)

| Address | Name | Type | Scale | Unit |
|---|---|---|---|---|
| 3130 | EPS R voltage | U16 | 0.1 | V |
| 3131 | EPS R current | U16 | 0.1 | A |
| 3132 | EPS S voltage | U16 | 0.1 | V |
| 3133 | EPS S current | U16 | 0.1 | A |
| 3134 | EPS T voltage | U16 | 0.1 | V |
| 3135 | EPS T current | U16 | 0.1 | A |
| 3136–37 | EPS R power | U32 | 0.1 | W |
| 3138–39 | EPS S power | U32 | 0.1 | W |
| 3140–41 | EPS T power | U32 | 0.1 | W |

### Energy Counters

| Address | Name | Type | Scale | Unit |
|---|---|---|---|---|
| 3049–50 | PV energy today | U32 | 0.1 | kWh |
| 3051–52 | PV energy total | U32 | 0.1 | kWh |
| 3053–54 | AC energy today | U32 | 0.1 | kWh |
| 3055–56 | AC energy total | U32 | 0.1 | kWh |
| 3176–77 | Battery discharge today | U32 | 0.1 | kWh |
| 3178–79 | Battery discharge total | U32 | 0.1 | kWh |
| 3180–81 | Battery charge today | U32 | 0.1 | kWh |
| 3182–83 | Battery charge total | U32 | 0.1 | kWh |
| 3184–85 | Grid import today | U32 | 0.1 | kWh |
| 3186–87 | Grid import total | U32 | 0.1 | kWh |
| 3188–89 | Grid export today | U32 | 0.1 | kWh |
| 3190–91 | Grid export total | U32 | 0.1 | kWh |
| 3192–93 | Load today | U32 | 0.1 | kWh |
| 3194–95 | Load total | U32 | 0.1 | kWh |

### Battery (Protocol II, SPH/SPA/storage types)

| Address | Name | Type | Scale | Unit |
|---|---|---|---|---|
| 3170 | Battery SOC | U16 | 1 | % |
| 3171 | Battery voltage | U16 | 0.1 | V |
| 3172 | Battery current | S16 | 0.1 | A | + charge, − discharge |
| 3173–74 | Battery power | S32 | 0.1 | W | + charge, − discharge |
| 3175 | BMS temperature | U16 | 0.1 | °C |

---

## 5. VPP Register Map

VPP registers are only present on devices with a non-zero value at FC03 30099 (VPP protocol version).

### VPP Holding Registers (FC03)

#### Device Identity (30000–30099)

| Address | Name | Type | Scale | Notes |
|---|---|---|---|---|
| 30000 | DTC code | U16 | 1 | See DTC table (Section 6) |
| 30001–10 | Model string | ASCII×10 | — | 20-char model name |
| 30011–20 | Serial number | ASCII×10 | — | 20-char serial |
| 30016–17 | Rated power | U32 | 1 | Watts |
| 30021–30 | Firmware version | ASCII×10 | — | DSP firmware string |
| 30031 | TP register | U16 | 1 | High byte = PV string count, low byte = phase count |
| 30099 | VPP protocol version | U16 | 1 | e.g. 202 = V2.02, 203 = V2.03 |

#### AC Power Control (30100–30299)

Key registers; full table in VPP spec Section 2.

| Address | Name | Type | Notes |
|---|---|---|---|
| 30150 | Active power control enable | U16 | 0=off |
| 30201 | Export limitation power | U16 | % of rated, signed |
| 30205 | Super export limitation enable | U16 | |
| 30209 | Per-phase active power enable | U16 | 0=off (default); when 1, FC04 31120–31125 become per-phase active power |

### VPP Input Registers (FC04)

#### Working State (31000–31009)

| Address | Name | Type | Scale | Notes |
|---|---|---|---|---|
| 31000 | Working state | U16 | 1 | See state table below |
| 31001 | Battery working state | U16 | 1 | 0=standby, 1=disconnected, 2=charging, 3=discharging |
| 31002 | Error code | U16 | 1 | |
| 31003 | Warning code | U16 | 1 | |
| 31008 | Active power output control | U16 | 1 | Current active power setpoint |

**Working state values (31000):**

| Value | Meaning |
|---|---|
| 0 | Standby |
| 1 | Self-test |
| 2 | Reserved |
| 3 | Fault |
| 4 | Firmware upgrade |
| 5 | PV online, battery offline (on-grid) |
| 6 | Battery online, PV online or offline (on-grid) |
| 7 | PV + battery online, off-grid |
| 8 | Battery online, PV offline, off-grid |
| 9 | Bypass operation |

#### PV Parameters (31010–31099)

Each PV string: voltage (U16, 0.1V) then current (U16, 0.1A). Up to 16 strings.

| Address | Name |
|---|---|
| 31010–11 | PV1 voltage / current |
| 31012–13 | PV2 voltage / current |
| 31014–15 | PV3 voltage / current |
| 31016–17 | PV4 voltage / current |
| 31018–19 | PV5 voltage / current |
| 31020–21 | PV6 voltage / current |
| 31022–23 | PV7 voltage / current |
| 31024–25 | PV8 voltage / current |
| 31058–59 | PV total input power | U32 | 0.1 | W |

The TP register (FC03 30031 high byte) gives the actual string count for the device.

#### AC Information (31100–31199)

| Address | Name | Type | Scale | Unit | Notes |
|---|---|---|---|---|---|
| 31100–01 | Active power total | S32 | 0.1 | W | Signed; + = export |
| 31102–03 | Reactive power total | S32 | 0.1 | var | |
| 31104 | Apparent power | U16 | 0.1 | VA | |
| 31105 | Grid frequency | U16 | 0.01 | Hz | |
| 31106 | Grid V_AB | U16 | 0.1 | V | Line-to-line |
| 31107 | Grid V_BC | U16 | 0.1 | V | |
| 31108 | Grid V_CA | U16 | 0.1 | V | |
| 31109 | Phase A current | U16 | 0.1 | A | |
| 31110 | Phase B current | U16 | 0.1 | A | |
| 31111 | Phase C current | U16 | 0.1 | A | |
| 31112–13 | Meter power | S32 | 0.1 | W | + = import from grid |
| 31114 | Inverter temperature | U16 | 0.1 | °C | |
| 31115 | Boost temperature | U16 | 0.1 | °C | |

**Dual-mode block 31118–31125** — behaviour depends on FC03 30209:

| 30209 | Address | Name | Type | Scale | Unit |
|---|---|---|---|---|---|
| 0 (default) | 31118–19 | Power to user today | U32 | 0.1 | kWh |
| 0 (default) | 31120–21 | Power to user total | U32 | 0.1 | kWh |
| 0 (default) | 31122–23 | Power to grid today | U32 | 0.1 | kWh |
| 0 (default) | 31124–25 | Power to grid total | U32 | 0.1 | kWh |
| 1 | 31118–19 | Power to user today | U32 | 0.1 | kWh | Still counter |
| 1 | 31120–21 | Active power phase R | S32 | 0.1 | W | Per-phase |
| 1 | 31122–23 | Active power phase S | S32 | 0.1 | W | |
| 1 | 31124–25 | Active power phase T | S32 | 0.1 | W | |

#### Battery Information (31200–31299, cluster 0)

Applies to MOD/MID-HU and SPH/SPA devices. Each additional battery cluster maps to 31300–31399, 31400–31499, 31500–31599.

| Address | Name | Type | Scale | Unit |
|---|---|---|---|---|
| 31200–01 | Battery charge power | U32 | 0.1 | W |
| 31202–03 | Battery discharge power | U32 | 0.1 | W |
| 31204–05 | Max allowable charge power | U32 | 0.1 | W |
| 31206–07 | Max allowable discharge power | U32 | 0.1 | W |
| 31208 | Battery voltage | U16 | 0.1 | V |
| 31209 | Battery current | S16 | 0.1 | A | + charge |
| 31210 | SOC | U16 | 1 | % |
| 31211 | SOH | U16 | 1 | % |
| 31212 | Battery capacity | U16 | 0.1 | kWh |
| 31214 | Battery temperature | S16 | 0.1 | °C |

---

## 6. DTC Code Table

Source: VPP Communication Protocol V2.03, Table 3-1.

| DTC | Family | Full name | EPS | Phases | Register profile |
|---|---|---|---|---|---|
| 3501 | SPH | SPH 3000–6000TL BL | ✓ | 1 | BASE_STORAGE |
| 3502 | SPH | SPH 3000–6000TL BL-UP | ✓ | 1 | BASE_STORAGE |
| 3503 | SPH | SPH 3000–6000TL HU | ✓ | 1 | BASE_STORAGE |
| 3504 | SPH | SPH 3000–6000TL HUB | ✓ | 1 | BASE_STORAGE |
| 3601 | SPH | SPH 4–10KTL3 BH-UP | ✓ | 3 | BASE_STORAGE |
| 3701 | SPA | SPA 1000–3000TL BL | ✓ | 1 | BASE_STORAGE |
| 3715 | SPA | SPA 3000–6000TL AU | ✓ | 1 | BASE_STORAGE |
| 3716 | SPA | SPA 3000–6000TL AUB | ✓ | 1 | BASE_STORAGE |
| 3725 | SPA | SPA 4–10KTL3 BH-UP | ✓ | 3 | BASE_STORAGE |
| 3735 | SPA | SPA 3000TL BL-UP | — | 1 | BASE_STORAGE |
| 5100 | MIN | MIN-XH / MIN 2500–6000TL-XH/XH2/XHE/XA | — | 1 | BASE_PROTO_II |
| 5200 | MIC | MIC 600–3300TL-X/X2/X2(Pro); MIN 2500–6000TL-X/X2 | — | 1 | BASE_PROTO_II |
| 5201 | MIN | MIN 7–10KTL-X/X2/X2(E) | — | 1 | BASE_PROTO_II |
| 5000 | MOD | MOD/MID/MAC-X (base) | — | 3 | BASE_PROTO_II_VPP |
| 5001 | MOD | MID 17–25KTL3-X; MID 20–30KTL3-X2; MID 25–50KTL3-X2 Pro; MID 30–40KTL3-X | — | 3 | BASE_PROTO_II_VPP |
| 5002 | MID | MID 33–36KTL3-X(Pro.E); MID 3–33KTL3-X3; MOD 3–15KTL3-X | — | 3 | BASE_PROTO_II_VPP |
| 5003 | MAC | MOD 3–15KTL3-X2(Pro); MOD 12–20KTL3-X2; MAC 30–70KTL3-X; MAC 15–36KTL3-XL | — | 3 | BASE_PROTO_II_VPP |
| 5400 | MOD | MOD-XH/MID-XH; MOD 3–10KTL3-XH/BP; MID 11–30KTL3-XH; MID 8–15KTL3-XHL/JP | — | 3 | BASE_PROTO_II_VPP |
| **5401** | **MOD** | **MOD/MID-HU; MOD 3–15KTL3-HU; MID 33–50KTL3-HU** | **✓** | **3** | **BASE_PROTO_II_VPP** |
| 5500 | MAX | MAX 50–100KTL3 LV/MV | — | 3 | BASE_PROTO_II_VPP |
| 5501 | MAX | MAX 175–253KTL3-X HV | — | 3 | BASE_PROTO_II_VPP |
| 5502 | MAX | MAX 80–150KTL3-X LV/MV; MAX 100–150KYL3-X2 LV/MV; MAX 320–350KTL3-X | — | 3 | BASE_PROTO_II_VPP |
| 5600 | WIS | WIS 100K-AM | — | 3 | BASE_PROTO_I_WIT |
| 5601 | WIT | WIT 50–100K-H/HE/HU/A/AE/AU; WIT 28–55K-H/HE/HU/A/AE/AU-US L2; WIT 29.9–50K-XHU | ✓ | 3 | BASE_PROTO_I_WIT |
| 5800 | WIS | WIS 210K | — | 3 | BASE_PROTO_II |
| 5801 | WIS | WIS 215K-AM | — | 3 | BASE_PROTO_II |

Bold row = device under test (DTC 5401, MOD 12KTL3-HU, verified 2026-05-09).

**Families without battery/storage registers:** 5000–5003 (MOD/MID/MAC-X), 5200–5201 (MIC/MIN-X), 5500–5502 (MAX), 5600 (WIS 100K-AM). Do not attempt to read FC04 31200+ on these.

---

## 7. Register Profiles

The proxy serves different FC03/FC04 ranges per profile.

### BASE_PROTO_II_VPP (MOD/MID-HU, MOD/MID-XH, MAX, etc.)

| FC | Ranges |
|---|---|
| FC03 | 0–124, 3000–3124, 3250–3374, 30000–30099 |
| FC04 | 3000–3124, 3125–3249, 3250–3374, 31000–31059, 31100–31125, 31200–31229 |

### BASE_PROTO_II (MIN-XH, MIC/MIN-X, WIS)

| FC | Ranges |
|---|---|
| FC03 | 0–124, 3000–3124, 3250–3374 |
| FC04 | 3000–3124, 3125–3249, 3250–3374 |

### BASE_STORAGE (SPH, SPA)

| FC | Ranges |
|---|---|
| FC03 | 0–124, 1000–1124 |
| FC04 | 0–124, 1000–1124 |

### BASE_PROTO_I_WIT (WIT, WIS 100K)

| FC | Ranges |
|---|---|
| FC03 | 0–124, 125–249, 875–999 |
| FC04 | 0–124, 125–249, 8000–8124 |

---

## 8. FC03 Holding Register Identity Block (0–124)

These are the inverter's own Protocol II holding registers, correctly bridged by the ShineWifi-X2 (contrary to earlier speculation). Notable fields:

| Address | Name | Type | Notes |
|---|---|---|---|
| 9–14 | DSP firmware version | ASCII×6 | e.g. `DO1.0ZBDC` |
| 28–29 | Module ID | U32 | High word = series code, low word = rated watts. May read 0 via ShineWifi. |
| 44 | TP register | U16 | High byte = PV string inputs, low byte = phase count |
| 121 | Device type | U16 | May reflect ShineWifi config (0x78 observed), not inverter type |

---

## 9. Proxy Architecture

This codebase runs a Modbus TCP proxy that:

1. **Probes** the inverter on startup to detect the DTC and select a driver.
2. **Caches** static registers (FC03 0–124, 30000–30099) in memory at boot.
3. **Polls** live input registers (FC04 3000+, 31000+) on each cycle.
4. **Serves** all ranges to Modbus clients on port 5020.
5. **Exports** telemetry to HTTP `/metrics` (Prometheus), MQTT, and InfluxDB.

The proxy prevents multiple clients from competing for the single ShineWifi connection.

---

## 10. Known Limitations & Observations (Device: MOD 12KTL3-HU)

- **FC03 30209 = 0** (default): per-phase active power override is not enabled. Registers 31120–31125 are energy counters, not per-phase watts.
- **FC03 30215 = 120**: EPS off-grid voltage target (120 VAC, US default from spec), present even on EU units.
- **Night/bypass behaviour**: When the inverter is in bypass mode (state 9, no PV, no battery), all current and power registers read 0. Grid voltages and frequency remain valid.
- **Daily energy counters reset at midnight** (00:00 local inverter time). Totals at 31120/21 and 31124/25 should be non-zero; if they read 0, the firmware may not implement these VPP registers on V2.02.
- **VPP protocol version = 202** (V2.02): the device was manufactured before V2.03, so V2.03-specific features (per-phase power gate, 30209–30215 block) are accessible in read mode but may not be controllable.
