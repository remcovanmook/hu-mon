import argparse
import json
import logging
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusIOException
from growatt.store import GrowattStore
from growatt.reading import GrowattReading

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
logger = logging.getLogger("growatt_collector")

def parse_u16(val):
    return val if val != 0xFFFF else 0

def parse_s16(val):
    if val == 0xFFFF: return 0
    return val - 0x10000 if val > 0x7FFF else val

def parse_u32(high, low):
    if high == 0xFFFF and low == 0xFFFF: return 0
    return (high << 16) | low

def parse_s32(high, low):
    if high == 0xFFFF and low == 0xFFFF: return 0
    val = (high << 16) | low
    return val - 0x100000000 if val > 0x7FFFFFFF else val

def poll_datalogger(ip: str, port: int, store: GrowattStore):
    client = ModbusTcpClient(ip, port=port, timeout=3.0)
    
    while True:
        start_time = time.time()
        try:
            if not client.is_socket_open():
                logger.info("Connecting to datalogger %s:%d", ip, port)
                client.connect()

            # Segment 1 (PV/Status) 3000-3024
            r1 = client.read_input_registers(3000, count=25, device_id=1)
            if r1.isError(): raise ModbusIOException("Failed to read Segment 1 (3000)")
            time.sleep(0.05)
            
            # Segment 2 (Grid/Load) 3030-3059
            r2 = client.read_input_registers(3030, count=30, device_id=1)
            if r2.isError(): raise ModbusIOException("Failed to read Segment 2 (3030)")
            time.sleep(0.05)

            # Segment 4 (Meter/EPS) 3120-3128
            r4 = client.read_input_registers(3120, count=9, device_id=1)
            if r4.isError(): raise ModbusIOException("Failed to read Segment 4 (3120)")
            time.sleep(0.05)
            
            # Segment 3 (Battery) 3170-3189
            r3 = client.read_input_registers(3170, count=20, device_id=1)
            if r3.isError(): raise ModbusIOException("Failed to read Segment 3 (3170)")
            
            reg1 = r1.registers
            reg2 = r2.registers
            reg4 = r4.registers
            reg3 = r3.registers

            reading = GrowattReading()
            reading.status_code = parse_u16(reg1[0])
            reading.pv_total_w = parse_u32(reg1[1], reg1[2]) / 10.0
            reading.pv1_v = parse_u16(reg1[3]) / 10.0
            reading.pv1_a = parse_u16(reg1[4]) / 10.0
            reading.pv1_w = parse_u32(reg1[5], reg1[6]) / 10.0
            reading.pv2_v = parse_u16(reg1[7]) / 10.0
            reading.pv2_a = parse_u16(reg1[8]) / 10.0
            reading.pv2_w = parse_u32(reg1[9], reg1[10]) / 10.0
            reading.pv3_v = parse_u16(reg1[11]) / 10.0
            reading.pv3_a = parse_u16(reg1[12]) / 10.0
            reading.pv3_w = parse_u32(reg1[13], reg1[14]) / 10.0
            reading.pv4_v = parse_u16(reg1[15]) / 10.0
            reading.pv4_a = parse_u16(reg1[16]) / 10.0
            reading.pv4_w = parse_u32(reg1[17], reg1[18]) / 10.0
            
            reading.grid_l1_v = parse_u16(reg2[0]) / 10.0
            reading.grid_l1_a = parse_u16(reg2[1]) / 10.0
            reading.grid_l2_v = parse_u16(reg2[4]) / 10.0
            reading.grid_l2_a = parse_u16(reg2[5]) / 10.0
            reading.grid_l3_v = parse_u16(reg2[8]) / 10.0
            reading.grid_l3_a = parse_u16(reg2[9]) / 10.0
            reading.grid_freq = parse_u16(reg2[12]) / 100.0
            

            
            reading.eps_p = parse_u32(reg4[0], reg4[1]) / 10.0
            reading.meter_total_w = parse_s32(reg4[1], reg4[2]) / 10.0
            reading.meter_l1_w = parse_s32(reg4[3], reg4[4]) / 10.0
            reading.meter_l2_w = parse_s32(reg4[5], reg4[6]) / 10.0
            reading.meter_l3_w = parse_s32(reg4[7], reg4[8]) / 10.0
            
            reading.bat_soc = parse_u16(reg3[0])
            reading.bat_v = parse_u16(reg3[1]) / 10.0
            reading.bat_i = parse_s16(reg3[2]) / 10.0
            reading.bat_p = parse_s32(reg3[3], reg3[4]) / 10.0
            
            # Energy Counters
            reading.pv_today_kwh = parse_u32(reg2[23], reg2[24]) / 10.0
            reading.pv_total_kwh = parse_u32(reg2[25], reg2[26]) / 10.0
            reading.grid_import_today_kwh = parse_u32(reg3[14], reg3[15]) / 10.0
            reading.grid_export_today_kwh = parse_u32(reg3[16], reg3[17]) / 10.0
            reading.load_today_kwh = parse_u32(reg3[18], reg3[19]) / 10.0
            
            # Use native house load register (3048-49)
            reading.load_p = parse_u32(reg2[18], reg2[19]) / 10.0

            # Package raw payload as a JSON dictionary for the Modbus Proxy
            raw_dict = {}
            for i, val in enumerate(reg1): raw_dict[str(3000 + i)] = val
            for i, val in enumerate(reg2): raw_dict[str(3030 + i)] = val
            for i, val in enumerate(reg4): raw_dict[str(3120 + i)] = val
            for i, val in enumerate(reg3): raw_dict[str(3170 + i)] = val
            reading.raw_payload = json.dumps(raw_dict).encode('utf-8')

            store.insert(reading)

        except (ConnectionException, ConnectionResetError, OSError) as e:
            logger.warning("Connection dropped (%s). Reconnecting...", type(e).__name__)
            client.close()
        except ModbusIOException as e:
            logger.error("Modbus read error: %s", e)
            client.close()
        except Exception as e:
            logger.exception("Unexpected error in polling loop")
            client.close()
            
        # Ensure strict 5-second interval
        elapsed = time.time() - start_time
        sleep_time = max(0.0, 5.0 - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

def run(ip: str, port: int, db_path: str):
    store = GrowattStore(db_path)
    logger.info("Starting robust collector targeting %s:%d", ip, port)
    poll_datalogger(ip, port, store)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", required=True, help="Datalogger IP")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--db", default="growatt.db")
    args = parser.parse_args()
    run(args.ip, args.port, args.db)
