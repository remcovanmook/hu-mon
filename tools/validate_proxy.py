#!/usr/bin/env python3
"""
tools/validate_proxy.py
~~~~~~~~~~~~~~~~~~~~~~~
Validate the growatt-proxy stack from the outside.

Connects to the local Modbus TCP proxy (default localhost:5020) and walks
every FC03/FC04 range the proxy claims to serve, reporting success/failure,
register count, and non-zero count per range.  Decodes a handful of key
telemetry values so a human can spot obvious scaling or sign errors.

Also checks the HTTP dashboard (/metrics endpoint if present, /api/history
for recent data).

Usage::

    # Server must already be running with the proxy on port 5020
    python tools/validate_proxy.py
    python tools/validate_proxy.py --host 127.0.0.1 --port 5020 --slave 1
    python tools/validate_proxy.py --http-port 8081

Exit code:
    0  All declared ranges responded and at least one range had non-zero data.
    1  One or more ranges returned errors, or all data was zero.
"""

import argparse
import sys
import time
import urllib.request
import urllib.error

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    sys.exit("pymodbus not installed.  Run: pip install pymodbus")


# ---------------------------------------------------------------------------
# Proxy register layout (must match the server's proxy_config output)
# FC03 ranges: (start, count, label)
# FC04 ranges: (start, count, label)
# ---------------------------------------------------------------------------

FC03_RANGES = [
    (0,     125, "Base block (firmware, DTC, RTP, TP, manuf.)"),
    (3000,  125, "Protocol II block A"),
    (3250,  125, "Protocol II block C"),
    (30000, 100, "VPP identity + protocol version"),
]

FC04_RANGES = [
    (3000,  125, "Protocol II block A (status, PV)"),
    (3125,  125, "Protocol II block B (US variant)"),
    (3250,  125, "Protocol II block C (EPS)"),
    (31000,  60, "VPP status + PV strings"),
    (31100,  26, "VPP AC / meter / freq / temp / kWh"),
    (31200,  30, "VPP battery live data"),
]

# ---------------------------------------------------------------------------
# Telemetry decode — read from FC04 VPP registers and sanity-check values.
# Plausibility bounds are generous; we just want to catch scaling errors.
# ---------------------------------------------------------------------------

_SANITY_CHECKS = [
    # (fc, start, idx_lo, idx_hi, scale, unit, name, lo_plausible, hi_plausible)
    # Grid frequency: FC04 31105, 0.01 Hz, expect 45–65 Hz
    (4, 31100, 5, None, 0.01, "Hz",   "Grid frequency",       45.0, 65.0),
    # L-L voltage RS: FC04 31106, 0.1 V, expect 300–430 V (3-phase)
    (4, 31100, 6, None, 0.1,  "V",    "Grid voltage L-AB",   300.0, 430.0),
    # Inverter temperature: FC04 31114, 0.1 °C, expect 5–90 °C
    (4, 31100, 14, None, 0.1, "°C",   "Inverter temp",        5.0,  90.0),
    # Active power: FC04 31100-31101, u32, 0.1 W, signed (pos=export)
    # We just check the pair is readable; sign and value not bounded tightly
    # Working state: FC04 31000, per VPP spec states 0-9:
    # 0=standby 1=self-test 2=reserved 3=fault 4=upgrade
    # 5=PV+bat-offline 6=bat+PV-online 7=PV+bat-offgrid
    # 8=bat-online-PV-offline 9=bypass
    (4, 31000, 0, None, 1.0,  "code", "Working state (0-9)",  0.0,  9.0),

]


def _u32(hi: int, lo: int) -> int:
    """Combine two 16-bit registers into an unsigned 32-bit value."""
    return (hi << 16) | lo


def _s32(hi: int, lo: int) -> int:
    """Combine two 16-bit registers into a signed 32-bit value."""
    v = _u32(hi, lo)
    return v - (1 << 32) if v >= (1 << 31) else v


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"
INFO = "\033[36m·\033[0m"


def _ok(msg: str) -> None:
    print(f"  {PASS}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {FAIL}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {WARN}  {msg}")


def _info(msg: str) -> None:
    print(f"  {INFO}  {msg}")


# ---------------------------------------------------------------------------
# Modbus probe
# ---------------------------------------------------------------------------

def _read(client, fc: int, start: int, count: int, slave: int):
    """
    Read *count* registers starting at *start* using function code *fc*.

    :param client: Connected ModbusTcpClient.
    :param fc:     3 (holding) or 4 (input).
    :param start:  Register base address.
    :param count:  Number of registers to read.
    :param slave:  Modbus slave / unit ID.
    :returns:      List of register values, or None on error.
    """
    try:
        if fc == 3:
            r = client.read_holding_registers(start, count=count, device_id=slave)
        else:
            r = client.read_input_registers(start, count=count, device_id=slave)
        if r.isError():
            return None
        return r.registers
    except Exception as exc:
        return None


def probe_modbus(host: str, port: int, slave: int) -> bool:
    """
    Walk all declared FC03/FC04 ranges and report results.

    :param host:  Proxy hostname or IP.
    :param port:  Proxy TCP port.
    :param slave: Modbus slave ID.
    :returns:     True if all mandatory ranges responded with non-zero data.
    """
    print(f"\n{'='*60}")
    print(f"  Modbus proxy  {host}:{port}  slave={slave}")
    print(f"{'='*60}")

    client = ModbusTcpClient(host, port=port, timeout=5)
    if not client.connect():
        print(f"  {FAIL}  Cannot connect to {host}:{port}")
        return False

    all_ok = True
    any_nonzero = False
    results: dict = {}

    for ranges, fc_label, fc in [
        (FC03_RANGES, "FC03 holding", 3),
        (FC04_RANGES, "FC04 input",   4),
    ]:
        print(f"\n  {fc_label}")
        print(f"  {'-'*55}")
        for start, count, label in ranges:
            regs = _read(client, fc, start, count, slave)
            if regs is None:
                _fail(f"{start:5d}–{start+count-1:5d}  ERROR   {label}")
                all_ok = False
            else:
                nz = sum(1 for v in regs if v != 0)
                status = PASS if nz > 0 else WARN
                tag = "OK" if nz > 0 else "all-zero"
                print(f"  {status}  {start:5d}–{start+count-1:5d}  "
                      f"{nz:3d}/{count} non-zero  {label}")
                if nz > 0:
                    any_nonzero = True
                results[(fc, start)] = regs

    # -----------------------------------------------------------------------
    # Telemetry sanity checks
    # -----------------------------------------------------------------------
    print(f"\n  Telemetry spot-checks")
    print(f"  {'-'*55}")
    for fc, base, idx_lo, idx_hi, scale, unit, name, lo, hi in _SANITY_CHECKS:
        regs = results.get((fc, base))
        if regs is None:
            _warn(f"{name}: register range not available")
            continue
        try:
            raw = regs[idx_lo]
            val = raw * scale
            ok = lo <= val <= hi
            mark = PASS if ok else FAIL
            print(f"  {mark}  {name}: {val:.2f} {unit}  "
                  f"(raw={raw}  bounds=[{lo}, {hi}])")
            if not ok:
                all_ok = False
        except IndexError:
            _warn(f"{name}: index {idx_lo} out of range for FC{fc} {base}")

    client.close()

    print()
    if not any_nonzero:
        _fail("All register ranges returned zero — server may not be polling yet")
        return False
    if all_ok:
        _ok("Proxy validation passed")
    else:
        _fail("One or more checks failed — see above")
    return all_ok


# ---------------------------------------------------------------------------
# HTTP endpoint checks
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 5) -> tuple:
    """
    Fetch *url* via HTTP GET.

    :returns: (status_code, body_text) or (None, error_string) on failure.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, str(exc)
    except Exception as exc:
        return None, str(exc)


def probe_http(host: str, port: int) -> bool:
    """
    Check HTTP endpoints served by growatt_server.

    Checks:
      /           Dashboard HTML present
      /api/history  JSON with at least one reading
      /metrics    Prometheus text format (expected future endpoint)

    :param host: Dashboard hostname.
    :param port: Dashboard HTTP port.
    :returns:    True if all existing endpoints responded correctly.
    """
    base = f"http://{host}:{port}"
    print(f"\n{'='*60}")
    print(f"  HTTP dashboard  {base}")
    print(f"{'='*60}\n")

    all_ok = True

    # Dashboard root
    status, body = _http_get(f"{base}/")
    if status == 200:
        _ok(f"GET /  → {status} ({len(body)} bytes)")
    else:
        _fail(f"GET /  → {status}: {body[:120]}")
        all_ok = False

    # History API
    status, body = _http_get(f"{base}/api/history?hours=1")
    if status == 200:
        try:
            import json
            data = json.loads(body)
            count = len(data.get("readings", data) if isinstance(data, dict) else data)
            if count > 0:
                _ok(f"GET /api/history  → {status} ({count} readings)")
            else:
                _warn(f"GET /api/history  → {status} but 0 readings (no data yet?)")
        except Exception:
            _ok(f"GET /api/history  → {status} (non-JSON or unexpected shape)")
    else:
        _fail(f"GET /api/history  → {status}")
        all_ok = False

    # Prometheus /metrics — not yet implemented; report as missing, not fail
    status, body = _http_get(f"{base}/metrics")
    if status == 200 and "# TYPE" in body:
        _ok(f"GET /metrics  → {status} (Prometheus format detected)")
    elif status == 404 or status is None:
        _warn(f"GET /metrics  → not implemented yet (404/unreachable)")
    else:
        _warn(f"GET /metrics  → {status} (unexpected response)")

    return all_ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Parse arguments and run Modbus proxy and HTTP endpoint validation.

    :returns: 0 on success, 1 on any failure.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host",      default="127.0.0.1",
                        help="Proxy / dashboard host (default: 127.0.0.1)")
    parser.add_argument("--port",      type=int, default=5020,
                        help="Modbus proxy port (default: 5020)")
    parser.add_argument("--slave",     type=int, default=1,
                        help="Modbus slave ID (default: 1)")
    parser.add_argument("--http-port", type=int, default=8081,
                        help="Dashboard HTTP port (default: 8081)")
    parser.add_argument("--no-http",   action="store_true",
                        help="Skip HTTP endpoint checks")
    args = parser.parse_args()

    modbus_ok = probe_modbus(args.host, args.port, args.slave)
    http_ok = True
    if not args.no_http:
        http_ok = probe_http(args.host, args.http_port)

    print()
    return 0 if (modbus_ok and http_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
