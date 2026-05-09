# Device abstraction layer, dual-driver architecture, Wye phasor dashboard

## Summary

This branch restructures the Growatt integration from a single-file polling
script into a layered, protocol-aware system with full test coverage. It also
extends the dashboard with 3-phase electrical quality visualisation and
replaces a hallucinated reference document with a verified one.

56 commits, 32 files changed, +6 117 / −600 lines.

---

## What changed

### 1 — Device abstraction layer (`growatt/drivers/`)

Introduced a clean driver interface (`base.py`) that separates hardware
detection from data decoding and proxy configuration. Both drivers implement
the same abstract contract, so `growatt_collector.py` is protocol-agnostic.

- **`drivers/registry.py`** — 5-stage auto-detection pipeline:
  1. Open TCP connection, probe slave ID.
  2. Read FC03 0–124 (universal holding block).
  3. Gate on FC03 30099 (VPP protocol version) to decide protocol family.
  4. Read FC03 44 (TP register) for authoritative phase count and MPPT count,
     overriding any DTC-inferred topology.
  5. Fall back to FC04 input block if FC03 is absent.

- **`drivers/growatt_vpp/driver.py`** — Full VPP Protocol V2.01/V2.02 driver.
  Reads 50+ telemetry fields including L–N voltages (Protocol II regs
  3026/3030/3034), L–L voltages (31106–31108), EPS, battery, temperature,
  and power quality. Derives V_LN from V_LL via phasor triangle when Protocol
  II regs are unavailable (`_ll_to_ln()`).

- **`drivers/growatt_mod_hu/driver.py`** — Legacy MOD-HU driver retained for
  non-VPP hardware compatibility.

- **`drivers/growatt_vpp/architecture.md`** — Architecture reference describing
  the memory layout, register block strategy, and probe sequence.

- **`modbus/codec.py`** — Shared register codec extracted to a top-level
  package; eliminates duplication between drivers.

### 2 — Modbus proxy (`growatt_modbus_server.py`)

Each driver exposes a `proxy_config()` method returning the register ranges it
can serve. The proxy server seeds a `SimDevice` from the driver's static
register cache so Modbus clients can read inverter data without polling the
hardware directly.

- `ProxyConfig` restructured as `{slave_id: {fc: [(start, count)]}}`.
- Proxy seeding from FC03 0–124 and FC03 3000–3124 at startup.
- Fixed SimData block overlap bug (pymodbus requires `count=1` per address).

### 3 — VPP DTC register profiles

- DTC table expanded to full V2.03 spec (Table 3-1).
- FC03 44 (TP) elevated to a named, mandatory probe stage — its result
  overrides topology inferred from the DTC, covering all non-VPP and
  Protocol II devices.
- FC03 30099 gates VPP detection; FC03 30060–30061 decode model family.
- Clear disambiguation between Module ID (FC03 28–29) and VPP DTC (FC03 30000).

### 4 — Dashboard: Grid Power tab additions

**3-phase Wye phasor diagram** (`dashboard/static/`):

- Canvas-rendered phasor diagram showing L1/L2/L3 voltage vectors with IEC
  EN 50160 tolerance rings (207 V / 230 V / 253 V) and a 200 V display base.
- Line-to-line chords annotated with measured V_LL values from registers
  31106–31108 (not derived from V_LN, eliminating round-trip error).
- Stat tables: phase voltages vs IEC 230 V nominal; line differentials vs
  IEC 400 V nominal; neutral offset (magnitude, angle, NEMA imbalance %).
- Mini polar diagram shows neutral offset vector inverted (offset point →
  centre); red dot marks current neutral position.
- `WYE_CSS` token cache refreshed on every theme toggle so canvas draws track
  dark/light/auto correctly.
- Canvas resize deferred to first tab-open (fixes zero-dimension init in hidden
  tab panels).

**Line-to-line voltage cards** (`grid-ll-cards`):

- Added RS/ST/TR sparkline cards sourced from registers 31106–31108.
- Card colors match wye chord colors (`--wye-l12/l13/l23`) for visual
  consistency.
- Section moved below the wye diagram; table row order matches card order
  (RS / ST / TR = L1–L2 / L2–L3 / L1–L3).

**PV string cleanup**:

- Removed non-existent PV4 from the frontend (color palette, dataset config,
  data buffers, sparkline loops, DOM updates).
- PV mini-chart row resized from 4-column to 3-column layout.

### 5 — Exporters (`growatt/influx_publisher.py`, `mqtt_publisher.py`)

Fixed field mapping regressions; added exporter validation so startup fails
fast rather than silently dropping metrics.

### 6 — Dashboard: `/metrics` endpoint

Prometheus text-format endpoint added to `dashboard/app.py` (v0.0.4). Exposes
all reading fields as gauges with `inverter_` prefix.

### 7 — Documentation (`docs/`)

- `docs/growatt-modbus-reference.md` — New verified reference document:
  - FC03 0–124 universal holding block (Protocol II V1.39).
  - FC03 3000–3124 TL-X/XH extended holding block (battery, AC charge,
    backup box registers from V1.39 spec).
  - FC03 44 (TP) universal topology probe.
  - 5-stage auto-detection pipeline with fallback chain.
  - Protocol II vs VPP register disambiguation.
  - DTC to phase/string topology mapping.
- `docs/shinewifi-x2-modbus.md` — Removed (contained fabricated register
  addresses not present on live hardware).

### 8 — Tools

- `tools/probe_phase_power.py` — Dual-mode register probe for 31118–31125
  (phase power, per-phase AC output verification).
- `tools/validate_proxy.py` — Validates proxy register ranges and HTTP
  endpoints against a running server.

### 9 — Test suite (`tests/`)

New test modules covering every major addition:

| File | What it covers |
|---|---|
| `test_codec.py` | Register codec encode/decode round-trips |
| `test_driver_vpp.py` | VPP driver telemetry parsing, DTC profiles, _ll_to_ln |
| `test_driver_mod_hu.py` | MOD-HU driver parsing, EPS, phase voltages |
| `test_growatt_base.py` | Base driver contract, ProxyConfig structure |
| `test_registry.py` | Detection pipeline, FC03 44 probe, fallback chain |
| `test_parser.py` | Extended to cover new register fields |

---

## Testing

```bash
# Unit tests
python3 -m pytest tests/ -v

# Live integration (requires inverter on network)
python3 growatt_server.py --device-ip <IP> --http-port 8081

# Proxy validation
python3 tools/validate_proxy.py --host localhost --port 8081
```

---

## Migration notes

- `growatt_collector.py` interface is unchanged externally; driver selection is
  now automatic via `registry.auto_select()`.
- Database schema: new columns `eps_l*_mean` added — running `store.py`
  against an existing DB applies a non-destructive `ALTER TABLE`.
- No new runtime dependencies beyond `aiomqtt` (already in requirements).
