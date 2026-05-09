#!/usr/bin/env python3
"""
probe_vpp_registers.py

Probes the VPP (V2.01) holding and input register ranges on a live inverter
and prints all non-zero values, annotated with their spec field names.

Requires a direct TCP connection to the ShineWifi-X2 datalogger (port 502).

Usage:
    python3 tools/probe_vpp_registers.py --host 172.28.2.36 [--slave 1]
"""

import argparse
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymodbus.client import ModbusTcpClient


# ---------------------------------------------------------------------------
# VPP V2.01 field annotations
# ---------------------------------------------------------------------------

HOLDING_FIELDS = {
    # Basic parameters 30000-30099
    30000: "DTC (device type code)",
    30001: "SN[0-14] — 15 ASCII words",
    30016: "Rated power Pn H (0.1W)",
    30017: "Rated power Pn L",
    30018: "Maximum active power Pmax H (0.1W)",
    30019: "Maximum active power Pmax L",
    30020: "Qmax fed-to-grid H (0.1VAR)",
    30021: "Qmax fed-to-grid L",
    30022: "Qmax absorption-from-grid H",
    30023: "Qmax absorption-from-grid L",
    30024: "Smax H (0.1VA)",
    30025: "Smax L",
    30026: "BDC rated charge/discharge power H (0.1W)",
    30027: "BDC rated charge/discharge power L",
    30028: "PV input max power H (0.1W)",
    30029: "PV input max power L",
    30030: "Battery type (0=lead, 1=lithium)",
    30060: "Machine model str[0]",
    30061: "Machine model str[1]",
    30062: "Version Num 1",
    30063: "Version Num 2",
    30064: "Version Num 3",
    30065: "M3 version str[0]",
    30066: "M3 version str[1]",
    30067: "M3 version num",
    30099: "VPP protocol version (201=V2.01)",
    # System order 30100-30149
    30100: "Control authority (0=off, 1=on)",
    30101: "On/off command (0=off, 1=on)",
    30102: "Country/region code",
    30112: "Mailing address (slave ID)",
    30113: "Baud rate (0=9600)",
    30115: "SYN enable",
    # AC power control 30150-30299
    30151: "Active power percentage derating (%)",
    30154: "Static active power limitation (%)",
    30155: "EPS offline enable",
    30156: "EPS offline frequency (0=50Hz)",
    30157: "EPS offline voltage",
    30160: "Fix Q (%)",
    30161: "Reactive power mode",
    30162: "Power factor",
    30200: "Export Limitation enable",
    30201: "Export Limitation power rate (%, signed)",
    30202: "Export Limitation failure power rate (%)",
    30203: "EMS communication failure time (s)",
    30204: "EMS communication failure enable",
    30205: "Super Export Limitation enable",
    30206: "Export Limitation change slope (*0.01% Pn/s)",
    30207: "Export Limitation single phase control enable",
    30208: "Export Limitation protection mode",
    # Battery control 30300-30499
    30300: "Battery cluster index",
    30404: "Charging cut-off SOC (%)",
    30405: "Online discharge cut-off SOC (%)",
    30406: "Load priority discharge cut-off SOC (%)",
    30407: "Remote power control enable",
    30408: "Remote power control charging time (min)",
    30409: "Remote charge/discharge power (%, signed)",
    30410: "AC charging enable",
    30474: "Actual control value charge/discharge power",
    30475: "Offline discharge cut-off SOC (%)",
    30496: "Battery charge stop voltage (0.1V)",
    30497: "Battery discharge stop voltage (0.1V)",
    30498: "Battery max charge current (0.1A)",
    30499: "Battery max discharge current (0.1A)",
}

INPUT_FIELDS = {
    # Working status 31000-31009
    31000: "Working state (0=standby..7=PV+bat offgrid)",
    31001: "Battery working status (0=standby..4=fault)",
    31002: "Priority of work (0=load, 1=bat, 2=grid)",
    31005: "Fault code",
    31006: "Fault sub code",
    31007: "Alarm code",
    31008: "Alarm sub code",
    # PV 31010-31058
    31010: "PV1 voltage (0.1V)",
    31011: "PV1 current (0.1A)",
    31012: "PV2 voltage (0.1V)",
    31013: "PV2 current (0.1A)",
    31014: "PV3 power H (0.1W)",
    31015: "PV3 current (0.1A)",
    31016: "PV4 voltage (0.1V)",
    31017: "PV4 current (0.1A)",
    31058: "PV input power H (0.1W)",
    31059: "PV input power L",
    # AC 31100-31129
    31100: "Active power H (0.1W, pos=export)",
    31101: "Active power L",
    31102: "Reactive power H",
    31103: "Reactive power L",
    31105: "Grid frequency (0.01Hz)",
    31106: "Grid voltage / line AB voltage (0.1V)",
    31107: "BC line voltage (0.1V)",
    31108: "CA line voltage (0.1V)",
    31109: "Grid current / A-phase (0.1A, signed)",
    31110: "B-phase current (0.1A)",
    31111: "C-phase current (0.1A)",
    31112: "Meter power H (0.1W, pos=import)",
    31113: "Meter power L",
    31114: "Inverter temperature (0.1°C)",
    31118: "Power to user daily H (0.1kWh)",
    31119: "Power to user daily L",
    31120: "Total power to user H",
    31121: "Total power to user L",
    31122: "Power to grid daily H (0.1kWh)",
    31123: "Power to grid daily L",
    31124: "Total power to grid H",
    31125: "Total power to grid L",
    # Battery 31200-31229
    31200: "Charge/discharge power H (0.1W, pos=chg)",
    31201: "Charge/discharge power L",
    31202: "Daily charge H (0.1kWh)",
    31203: "Daily charge L",
    31204: "Cumulative charge H (0.1kWh)",
    31205: "Cumulative charge L",
    31206: "Daily discharge H (0.1kWh)",
    31207: "Daily discharge L",
    31208: "Cumulative discharge H (0.1kWh)",
    31209: "Cumulative discharge L",
    31210: "Max allowable charge power H (0.1W)",
    31211: "Max allowable charge power L",
    31212: "Max allowable discharge power H",
    31213: "Max allowable discharge power L",
    31214: "Battery voltage (0.1V)",
    31215: "Battery current H (0.1A, pos=chg)",
    31216: "Battery current L",
    31217: "SOC (%)",
    31218: "SOH (%)",
    31219: "Battery capacity (FCC) H (Ah)",
    31220: "Battery capacity (FCC) L",
    31223: "Battery temperature (0.1°C)",
    31225: "Cluster sum",
    31226: "Single cluster module number",
    31227: "Module rated voltage (0.1V)",
    31228: "Module rated capacity (0.1Ah)",
}


def _read_fc3(client, start, count, slave):
    """Read holding registers (FC 03) and return list or None on error."""
    r = client.read_holding_registers(start, count=count, device_id=slave)
    if r.isError():
        return None
    return r.registers


def _read_fc4(client, start, count, slave):
    """Read input registers (FC 04) and return list or None on error."""
    r = client.read_input_registers(start, count=count, device_id=slave)
    if r.isError():
        return None
    return r.registers


def _dump(regs, base, fields, show_zeros=False):
    """Print annotated register dump."""
    for i, v in enumerate(regs):
        addr = base + i
        if v == 0 and not show_zeros:
            continue
        label = fields.get(addr, "")
        print(f"  {addr}: {v:6d}  0x{v:04X}  {label}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="ShineWifi-X2 IP address")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--slave", type=int, default=1)
    parser.add_argument("--show-zeros", action="store_true",
                        help="Also print zero-valued registers")
    args = parser.parse_args()

    client = ModbusTcpClient(args.host, port=args.port, timeout=5)
    if not client.connect():
        print(f"ERROR: Could not connect to {args.host}:{args.port}")
        sys.exit(1)
    print(f"Connected to {args.host}:{args.port} slave={args.slave}")

    PAUSE = 0.2  # seconds between requests

    # -----------------------------------------------------------------------
    # Holding registers (FC 03)
    # -----------------------------------------------------------------------
    sections = [
        ("Basic params / identity 30000-30099",   30000, 100),
        ("System order control  30100-30149",      30100, 50),
        ("AC power control      30150-30299",      30150, 61),  # 30150-30210
        ("Battery control       30300-30410",      30300, 111),
        ("Battery schedule      30411-30499",      30411, 89),
    ]

    for title, start, count in sections:
        print(f"\n=== FC03 Holding: {title} ===")
        regs = _read_fc3(client, start, count, args.slave)
        if regs is None:
            print(f"  [ERROR — range not accessible]")
        else:
            nz = sum(1 for v in regs if v != 0)
            print(f"  [{nz} non-zero of {len(regs)} registers]")
            _dump(regs, start, HOLDING_FIELDS, args.show_zeros)
        time.sleep(PAUSE)

    # -----------------------------------------------------------------------
    # Input registers (FC 04)
    # -----------------------------------------------------------------------
    input_sections = [
        ("Working status        31000-31009", 31000, 10),
        ("PV params             31010-31059", 31010, 50),
        ("AC information        31100-31129", 31100, 30),
        ("Battery info 1        31200-31229", 31200, 30),
    ]

    for title, start, count in input_sections:
        print(f"\n=== FC04 Input: {title} ===")
        regs = _read_fc4(client, start, count, args.slave)
        if regs is None:
            print(f"  [ERROR — range not accessible]")
        else:
            nz = sum(1 for v in regs if v != 0)
            print(f"  [{nz} non-zero of {len(regs)} registers]")
            _dump(regs, start, INPUT_FIELDS, args.show_zeros)
        time.sleep(PAUSE)

    client.close()
    print("\nProbe complete.")


if __name__ == "__main__":
    main()
