import argparse
import time
from pymodbus.client import ModbusTcpClient

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", required=True, help="Datalogger IP")
    parser.add_argument("--port", type=int, default=502)
    args = parser.parse_args()

    print(f"[*] Attempting to connect to {args.ip}:{args.port}...")
    client = ModbusTcpClient(args.ip, port=args.port, timeout=3.0)
    
    if not client.connect():
        print("[!] Failed to establish TCP connection.")
        return

    print("[*] TCP socket open. Requesting Segment 1 (Reg 3000, Count 25)...")
    try:
        response = client.read_input_registers(3000, count=25, device_id=1)
        
        if response.isError():
            print(f"[!] Modbus Error: {response}")
        else:
            reg = response.registers
            status = reg[0]
            
            # 0xFFFF check for night mode
            if status == 0xFFFF:
                status = 0
                pv_watts = 0.0
            else:
                pv_watts = ((reg[1] << 16) | reg[2]) / 10.0
                
            status_map = {0: "WAITING", 1: "NORMAL", 3: "FAULT", 4: "FLASHING"}
            
            print("\n--- READ SUCCESS ---")
            print(f"Status Code:   {status} ({status_map.get(status, 'UNKNOWN')})")
            print(f"Total PV Power:{pv_watts} W")
            print(f"Raw Registers: {reg[:5]}...")
            
    except Exception as e:
        print(f"[!] Exception during Modbus transaction: {e}")
    finally:
        client.close()
        print("[*] Connection closed cleanly.")

if __name__ == '__main__':
    main()
