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
    client = ModbusTcpClient(ip, port=port)
    client.connect()
    
    # Read static configuration once at startup
    bat_nominal_kwh = None
    inverter_model = "Unknown"
    inverter_serial = "Unknown"
    inverter_firmware = "Unknown"
    inverter_rated_power_w = 0

    while bat_nominal_kwh is None:
        try:
            r_config = client.read_holding_registers(1005, count=1, device_id=1)
            if not r_config.isError():
                bat_nominal_kwh = r_config.registers[0] / 10.0
                logging.info(f"Discovered APX Battery Capacity: {bat_nominal_kwh} kWh")
            else:
                logging.warning("Failed to read battery capacity, retrying...")
                time.sleep(2)
                continue

            # Read Legacy serial OR new serial, and read Firmware
            r_meta = client.read_holding_registers(9, count=50, device_id=1)
            # Read New Serial Number from 3001 (15 Regs)
            r_serial = client.read_holding_registers(3001, count=15, device_id=1)
            
            if not r_meta.isError() and not r_serial.isError():
                regs_meta = r_meta.registers
                regs_ser = r_serial.registers
                
                def decode_ascii(reg_list):
                    b = bytearray()
                    for r in reg_list:
                        b.extend(r.to_bytes(2, 'big'))
                    return b.decode('ascii', 'ignore').replace('\x00', '').strip()
                
                inverter_firmware = decode_ascii(regs_meta[0:6])     # 9-14
                inverter_serial = decode_ascii(regs_ser)        # 3001-3015
                
                # Algorithmic Module ID decode (Reg 28-29 = index 19-20)
                module_id = (regs_meta[19] << 16) | regs_meta[20]
                if module_id == 0:
                    # Fallback if Modbus proxy zeros it out
                    inverter_model = "MOD 12KTL3-HU"
                    inverter_rated_power_w = 12000
                else:
                    series_code = (module_id >> 16) & 0xFFFF
                    power_watts = module_id & 0xFFFF
                    series_map = {0x05: "MIN", 0x0B: "MOD", 0x0C: "MID", 0x0D: "SPH", 0x0E: "SPA", 0x0F: "MIC", 0x10: "MAC", 0x11: "MAX"}
                    series_prefix = series_map.get(series_code, "Unknown")
                    if series_prefix == "MOD" and power_watts >= 3000:
                        inverter_model = f"{series_prefix} {int(power_watts/1000)}KTL3-HU"
                    else:
                        inverter_model = f"{series_prefix} {power_watts}W"
                    inverter_rated_power_w = power_watts * 10 if power_watts < 1000 else power_watts
                
                logging.info(f"Discovered Device: {inverter_model} (Serial: {inverter_serial}) FW: {inverter_firmware}")
                break

        except Exception as e:
            logging.warning(f"Error reading config: {e}")
            time.sleep(2)

    while True:
        start_time = time.time()
        try:
            if not client.is_socket_open():
                logger.info("Connecting to datalogger %s:%d", ip, port)
                client.connect()

            # Segment 1 (PV/Status) 3000-3024
            r1 = client.read_input_registers(3000, count=30, device_id=1)
            if r1.isError(): raise ModbusIOException("Failed to read Segment 1 (3000)")
            time.sleep(0.05)
            
            # Segment 2 (Grid) 3030-3109
            r2 = client.read_input_registers(3030, count=80, device_id=1)
            if r2.isError(): raise ModbusIOException("Failed to read Segment 2 (3030)")
            time.sleep(0.05)

            # Segment 4 (Meter/EPS/Temp) 3110-3154
            r4 = client.read_input_registers(3110, count=45, device_id=1)
            
            # Segment 5 (Low Block Mirror Hunt) 0-124
            r5 = client.read_input_registers(0, count=125, device_id=1)
            
            # Segment 3 (Battery) 3170-3189
            r3 = client.read_input_registers(3170, count=20, device_id=1)

            if r1.isError() or r2.isError() or r3.isError() or r4.isError() or r5.isError():
                time.sleep(1)
                continue
                
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
            
            # Auto-detect Frankenstein Shifted Profile using Frequency North Star
            # If Freq is at 3025 and L1 V is at 3026, the entire grid block is shifted.
            freq_3025 = parse_u16(reg1[25]) if len(reg1) > 25 else 0
            v_3026 = parse_u16(reg1[26]) if len(reg1) > 26 else 0
            
            if freq_3025 > 4000 and v_3026 > 1000:
                # Shifted Profile
                reading.grid_freq = freq_3025 / 100.0
                reading.grid_l1_v = v_3026 / 10.0
                reading.grid_l1_a = parse_u16(reg1[27]) / 10.0
                reading.grid_l2_v = parse_u16(reg2[0]) / 10.0
                reading.grid_l2_a = parse_u16(reg2[1]) / 10.0
                reading.grid_l3_v = parse_u16(reg2[4]) / 10.0
                reading.grid_l3_a = parse_u16(reg2[5]) / 10.0
            else:
                # Standard Profile
                reading.grid_freq = parse_u16(reg2[12]) / 100.0
                reading.grid_l1_v = parse_u16(reg2[0]) / 10.0
                reading.grid_l1_a = parse_u16(reg2[1]) / 10.0
                reading.grid_l2_v = parse_u16(reg2[4]) / 10.0
                reading.grid_l2_a = parse_u16(reg2[5]) / 10.0
                reading.grid_l3_v = parse_u16(reg2[8]) / 10.0
                reading.grid_l3_a = parse_u16(reg2[9]) / 10.0
                
            reading.fault_code = parse_u16(reg2[61])
            
            # Temperature is at 3094 and 3095 (shift of -20), which is reg2[64] and reg2[65]
            reading.inverter_temp = parse_u16(reg2[64]) / 10.0
            reading.boost_temp = parse_u16(reg2[65]) / 10.0
            
            # Segment 4 contains Temp, EPS and Meter. Starts at 3110.
            reg4 = r4.registers if len(r4.registers) >= 45 else [0]*45
            
            # 3118 is reg4[8]
            reading.eps_l1_v = parse_u16(reg4[8]) / 10.0
            
            # 3120 is reg4[10]
            reading.eps_p = parse_u32(reg4[10], reg4[11]) / 10.0
            reading.meter_total_w = parse_s32(reg4[11], reg4[12]) / 10.0
            
            # 3130 is reg4[20]
            reading.eps_l2_v = parse_u16(reg4[20]) / 10.0
            reading.eps_l1_a = parse_u16(reg4[21]) / 10.0  # 3131
            reading.eps_l3_v = parse_u16(reg4[22]) / 10.0  # 3132
            reading.eps_l2_a = parse_u16(reg4[23]) / 10.0  # 3133
            reading.eps_l3_a = parse_u16(reg4[25]) / 10.0  # 3135
            reading.meter_l1_w = parse_s32(reg4[13], reg4[14]) / 10.0
            reading.meter_l2_w = parse_s32(reg4[15], reg4[16]) / 10.0
            reading.meter_l3_w = parse_s32(reg4[17], reg4[18]) / 10.0
            
            reading.bat_soc = parse_u16(reg3[0])
            reading.bat_v = parse_u16(reg3[1]) / 10.0
            reading.bat_i = parse_s16(reg3[2]) / 10.0
            reading.bat_p = parse_s32(reg3[3], reg3[4]) / 10.0
            
            # Energy Counters
            reading.pv_today_kwh = parse_u32(reg2[19], reg2[20]) / 10.0     # 3049-3050
            reading.pv_total_kwh = parse_u32(reg2[21], reg2[22]) / 10.0     # 3051-3052
            
            # Additional AC Energy counters if needed later (3053-3056)
            # reading.eac_today = parse_u32(reg2[23], reg2[24]) / 10.0
            
            reading.grid_import_today_kwh = parse_u32(reg3[14], reg3[15]) / 10.0
            reading.grid_export_today_kwh = parse_u32(reg3[16], reg3[17]) / 10.0
            reading.load_today_kwh = parse_u32(reg3[18], reg3[19]) / 10.0
            reading.bat_discharge_today_kwh = parse_u32(reg3[6], reg3[7]) / 10.0
            reading.bat_charge_today_kwh = parse_u32(reg3[10], reg3[11]) / 10.0
            
            # Mathematically derive instantaneous load (safest and most accurate)
            reading.load_p = reading.pv_total_w - reading.meter_total_w - reading.bat_p
            reading.bat_nominal_kwh = bat_nominal_kwh
            reading.inverter_model = inverter_model
            reading.inverter_serial = inverter_serial
            reading.inverter_firmware = inverter_firmware
            reading.rated_power_w = inverter_rated_power_w

            # Package raw payload as a JSON dictionary for the Modbus Proxy
            raw_dict = {}
            for i, val in enumerate(reg1): raw_dict[str(3000 + i)] = val
            for i, val in enumerate(reg2): raw_dict[str(3030 + i)] = val
            for i, val in enumerate(reg4): raw_dict[str(3110 + i)] = val
            for i, val in enumerate(reg3): raw_dict[str(3170 + i)] = val
            for i, val in enumerate(r5.registers): raw_dict[str(i)] = val
            reading.raw_payload = json.dumps(raw_dict).encode('utf-8')

            import dataclasses

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
