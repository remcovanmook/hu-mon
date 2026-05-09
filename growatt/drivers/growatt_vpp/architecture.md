# GrowattVppDriver Architecture

## Overview

`GrowattVppDriver` implements telemetry collection for Growatt inverters that
support VPP (Virtual Power Plant) Protocol V2.01 or later.  It replaces the
Protocol II driver (`GrowattModHuDriver`) as the preferred driver for these
devices, with Protocol II FC04 used only for data that has no VPP equivalent.

Target hardware confirmed: **MOD 12KTL3-HU** via ShineWifi-X2 TCP gateway.

---

## Register Sources

| Priority | FC | Address range | Purpose |
|---|---|---|---|
| Primary | FC03 | 30000–30099 | VPP identity + control (DTC, serial, rated power) |
| Primary | FC04 | 31000–31599 | VPP telemetry (status, PV, AC, battery, energy) |
| Supplement | FC04 | 3049–3095 | Protocol II: PV energy kWh + boost temp |
| Supplement | FC04 | 3130–3159 | Protocol II: EPS V/A/power (has_eps only) |
| Not used | FC03 | 0–124 | ShineWifi-X2 own registers — not inverter data |

---

## Probe Pipeline

The registry runs five stages at startup:

```
Stage 3c (added): FC03 30000 → ctx.vpp_dtc
```

`GrowattVppDriver._probe_series()` returns True when:
1. `_is_growatt()` passes (Protocol II FC04 3000 status register in [0,10])
2. `ctx.vpp_dtc` is a known entry in `_VPP_DTC_TABLE`

This allows `GrowattModHuDriver` to remain in the registry as a fallback for
devices without VPP support.

---

## DTC Table

Device Type Codes (FC03 30000) map to product family metadata:

| DTC | Series | has_eps | phases |
|---|---|---|---|
| 5400 | MOD | False | 3 |
| 5401 | MOD | True | 3 |  ← live device (MOD 12KTL3-HU) |
| 5601 | WIT | True | 3 |
| 3601 | SPH | False | 1 |
| 5201 | MIN | False | 1 |
| 5200 | MIC | False | 1 |
| … | … | … | … |

Model string is constructed algorithmically: `{series} {kW}KTL{phases}-{suffix}`
where suffix is `HU` (has_eps) or `XH`.

---

## Poll Segments

Each call to `read_registers()` issues five FC04 reads:

```
S1  31000–31059  60 regs  Status + PV strings + total PV power   MANDATORY
S2  31100–31125  26 regs  AC / meter / grid / temp / energy kWh  MANDATORY
S3  31200–31229  30 regs  Battery 1 BMS                          soft-fail
S4  3049–3095    47 regs  PV energy kWh + boost_temp             soft-fail
S5  3130–3159    30 regs  EPS V/A + total power (has_eps only)   soft-fail
```

All counts are ≤ 64 registers (ShineWifi-X2 single-request limit).

---

## Register Mapping

### PV Strings (S1, 3-phase layout)

VPP stores 2 registers per string (V + A) for 3-phase inverters.
Per-string wattage is computed as `P = V × I` (DC, no power factor).

```
31010  PV1 voltage  0.1V
31011  PV1 current  0.1A   → pv1_w = pv1_v × pv1_a
31012  PV2 voltage  0.1V
31013  PV2 current  0.1A
31014  PV3 voltage  0.1V
31015  PV3 current  0.1A
31016  PV4 voltage  0.1V
31017  PV4 current  0.1A
31058–31059  Total PV power  INT32, 0.1W
```

Note: single-phase VPP devices use a 4-register layout (V + A + Power_H + Power_L)
defined in `vpp_v201.py` of the reference HA integration.  This driver targets
3-phase MOD/MID only and uses the 2-register layout.

### Grid Voltages

VPP stores **L-L voltages** (AB, BC, CA ≈ 428V on this device), not L-N.
`grid_l1_v / l2_v / l3_v` in `GrowattReading` hold L-L values.
Dashboard consumers must label them "Line voltage (AB/BC/CA)".

### Power Factor and Per-Phase Power

```python
pf = ac_active_w / sqrt(ac_active_w² + ac_reactive_var²)

meter_l1_w = (grid_l1_v / √3) × grid_l1_a × pf
meter_l2_w = (grid_l2_v / √3) × grid_l2_a × pf
meter_l3_w = (grid_l3_v / √3) × grid_l3_a × pf
```

Approximation: assumes PF is uniform across phases.  Accurate for balanced
3-phase grid-tied operation.

### Meter Power Sign Convention

| Source | Positive means |
|---|---|
| VPP 31112–31113 | Import from grid |
| `GrowattReading.meter_total_w` | Export to grid |

The driver sign-inverts: `meter_total_w = -(raw VPP value / 10.0)`.

### Battery (S3)

The full S3 block (31200–31229) is skipped if all registers return zero,
which is the expected state when no battery is attached.  When a battery
is present, the block contains live charge/discharge power, SOC, voltage,
current, and energy counters.

---

## State Caching

`_has_eps` is set by `read_device_info()` from the DTC table and cached on
the driver instance.  `read_registers()` uses it to gate S5 — avoiding an
unnecessary TCP round-trip when the device has no EPS output.

---

## Deferred

- **Control surface** (FC03 30200, 30407, 30409): export limiting, remote
  charge/discharge.  Must check Control Authority (30100) before any write.
- **Multi-battery clusters** (31300–31599): same layout as 31200–31299.
  Implement when a second battery is attached and registers can be verified.
- **`grid_import_today_kwh`**: no VPP register; zero for v1.
