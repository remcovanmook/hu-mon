import json
import logging
from pymodbus.simulator import SimDevice, SimData, DataType
from pymodbus.server import StartTcpServer
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_modbus_server")

def run(store: GrowattStore, port: int = 5020):
    # Growatt MOD 12KTL3-HU primary registers span from 3000 to ~3200
    data = SimData(address=3000, count=200, values=[0]*200, datatype=DataType.REGISTERS)

    async def update_registers(func_code, start_address, address, count, registers, values):
        if values is None:  # This is a read request
            raw_bytes = store.get_latest_registers()
            if raw_bytes:
                try:
                    cache = json.loads(raw_bytes.decode('utf-8'))
                    # Inject cached live data natively into the simulator's memory block
                    for i in range(count):
                        reg_addr = address + i
                        offset = reg_addr - start_address
                        if 0 <= offset < len(registers):
                            registers[offset] = cache.get(str(reg_addr), 0)
                except Exception as e:
                    logger.error("Failed to decode cache: %s", e)
        return None

    device = SimDevice(id=1, simdata=[data], action=update_registers)
    
    logger.info("Starting Modbus TCP Mimic Server on 0.0.0.0:%d", port)
    StartTcpServer(context=device, address=("0.0.0.0", port))
