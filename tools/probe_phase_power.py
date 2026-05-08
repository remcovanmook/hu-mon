#!/usr/bin/env python3
"""
tools/probe_phase_power.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Check whether per-phase R/S/T active power registers are available.

V2.03 VPP spec defines a dual-mode block at FC04 31118-31125:
  30209 == 0 (default): energy counters (daily/total kWh)
  30209 == 1:           per-phase R/S/T active power (0.1 W, signed)

This script reads FC03 30209 from the proxy to determine which mode is
active, then decodes 31118-31125 accordingly.  It also reads the direct
device if --device-ip is given, to cross-check against the proxy.

Usage::
    python tools/probe_phase_power.py                     # proxy at localhost:5020
    python tools/probe_phase_power.py --host 127.0.0.1   # same
    python tools/probe_phase_power.py --device-ip 172.28.2.36  # device direct
"""

import argparse
import sys

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    sys.exit("pymodbus not installed")


def _u32(h: int, l: int) -> int:
    return (h << 16) | l


def _s32(h: int, l: int) -> int:
    v = _u32(h, l)
    return v - (1 << 32) if v >= (1 << 31) else v


def probe(host: str, port: int, slave: int, label: str) -> None:
    """
    Read the 30209 gate and 31118-31125 block from a Modbus TCP endpoint.

    :param host:  Hostname or IP.
    :param port:  TCP port.
    :param slave: Modbus slave ID.
    :param label: Display label for the source (e.g. 'proxy' or 'device').
    """
    print(f"\n{'='*60}")
    print(f"  {label}  {host}:{port}  slave={slave}")
    print(f"{'='*60}")

    client = ModbusTcpClient(host, port=port, timeout=5)
    if not client.connect():
        print(f"  ERROR: cannot connect to {host}:{port}")
        return

    # --- Gate register FC03 30209 ---
    r = client.read_holding_registers(30209, count=7, device_id=slave)
    if not r.isError():
        gate = r.registers[0]
        print(f"\n  FC03 30209  (per-phase active power enable):  {gate}")
        for i, v in enumerate(r.registers):
            if v:
                print(f"    30209+{i} = {v}")
        if gate:
            print("  → mode: per-phase R/S/T active power (31120-31125)")
        else:
            print("  → mode: energy counters (31118-31125 = daily/total kWh)")
    else:
        print(f"  FC03 30209-30215: ERROR {r}")
        gate = 0

    # --- Active power + dual-mode block FC04 31100-31125 ---
    r = client.read_input_registers(31100, count=26, device_id=slave)
    if not r.isError():
        regs = r.registers
        print(f"\n  FC04 31100–31125:")

        # Always-present
        ap_total = _s32(regs[0], regs[1])
        print(f"    31100/01  Active power total:      {ap_total * 0.1:+8.1f} W")
        print(f"    31105     Grid frequency:           {regs[5] * 0.01:.2f} Hz")
        print(f"    31106     Grid voltage L-AB:        {regs[6] * 0.1:.1f} V")
        print(f"    31107     Grid voltage L-BC:        {regs[7] * 0.1:.1f} V")
        print(f"    31108     Grid voltage L-CA:        {regs[8] * 0.1:.1f} V")
        print(f"    31109     Current phase A:          {regs[9] * 0.1:.2f} A")
        print(f"    31110     Current phase B:          {regs[10] * 0.1:.2f} A")
        print(f"    31111     Current phase C:          {regs[11] * 0.1:.2f} A")
        mp = _s32(regs[12], regs[13])
        print(f"    31112/13  Meter power:             {mp * 0.1:+8.1f} W  (pos=import)")
        print(f"    31114     Inverter temp:            {regs[14] * 0.1:.1f} °C")

        # Dual-mode block
        print(f"\n  FC04 31118–31125 (dual-mode):")
        r18 = _u32(regs[18], regs[19])
        r20 = _s32(regs[20], regs[21])
        r22 = _s32(regs[22], regs[23])
        r24 = _s32(regs[24], regs[25])
        raw = [(31118 + i, regs[18 + i]) for i in range(8)]
        for addr, v in raw:
            print(f"    {addr}: {v:6d}  (0x{v:04X})")

        print(f"\n  Interpretation:")
        if not gate:
            print(f"    31118/19  Power to user daily:    {r18 * 0.1:.2f} kWh")
            print(f"    31120/21  Total power to user:    {r20 * 0.1:.2f} kWh")
            print(f"    31122/23  Power to grid daily:    {r22 * 0.1:.2f} kWh")
            print(f"    31124/25  Total power to grid:    {r24 * 0.1:.2f} kWh")
        else:
            print(f"    31118/19  Power to user daily:    {r18 * 0.1:.2f} kWh (still counter)")
            print(f"    31120/21  Active power R:         {r20 * 0.1:+.1f} W")
            print(f"    31122/23  Active power S:         {r22 * 0.1:+.1f} W")
            print(f"    31124/25  Active power T:         {r24 * 0.1:+.1f} W")

        # Inferred per-phase from V/I if no gate
        if not gate:
            print(f"\n  Inferred per-phase power from V×I (approximate):")
            vab = regs[6] * 0.1
            vbc = regs[7] * 0.1
            vca = regs[8] * 0.1
            # Line-to-neutral ≈ V_LL / √3
            import math
            vln = vab / math.sqrt(3)
            ia = regs[9] * 0.1
            ib = regs[10] * 0.1
            ic = regs[11] * 0.1
            print(f"    V_LN ≈ {vln:.1f} V  (from V_AB={vab:.1f} V)")
            print(f"    Phase A: {vln * ia:+.1f} W  (I={ia:.2f} A)")
            print(f"    Phase B: {vln * ib:+.1f} W  (I={ib:.2f} A)")
            print(f"    Phase C: {vln * ic:+.1f} W  (I={ic:.2f} A)")
            print(f"    Sum:     {vln * (ia + ib + ic):+.1f} W  (vs total {ap_total * 0.1:+.1f} W)")
    else:
        print(f"  FC04 31100-31125: ERROR {r}")

    client.close()


def main() -> None:
    """Parse arguments and run the phase power probe."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host",      default="127.0.0.1",
                        help="Proxy/device host (default: 127.0.0.1)")
    parser.add_argument("--port",      type=int, default=5020,
                        help="Proxy port (default: 5020)")
    parser.add_argument("--slave",     type=int, default=1)
    parser.add_argument("--device-ip", default="",
                        help="Also probe the real inverter directly on port 502")
    args = parser.parse_args()

    probe(args.host, args.port, args.slave, "proxy")
    if args.device_ip:
        probe(args.device_ip, 502, args.slave, "device (direct)")


if __name__ == "__main__":
    main()
