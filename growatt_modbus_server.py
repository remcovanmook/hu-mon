import json
import logging
from pymodbus.datastore import ModbusSparseDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.server import StartTcpServer
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_modbus_server")

class GrowattDataBlock(ModbusSparseDataBlock):
    def __init__(self, store: GrowattStore):
        # Initialize with dummy values so the server can start
        super().__init__({3000: 0})
        self.store = store
        self._cache = {}

    def getValues(self, address, count=1):
        raw_bytes = self.store.get_latest_registers()
        if raw_bytes:
            try:
                # Cache is updated atomically from the serialized payload
                self._cache = json.loads(raw_bytes.decode('utf-8'))
            except Exception as e:
                logger.error("Failed to decode raw payload: %s", e)

        # Modbus protocol expects an array of values
        # If register is not in cache, fallback to 0 (or 0xFFFF, but 0 is safer)
        return [self._cache.get(str(address + i), 0) for i in range(count)]

def run(store: GrowattStore, port: int = 5020):
    block = GrowattDataBlock(store)
    # zero_mode=True maps requested Modbus address exactly to dictionary key
    slave_context = ModbusSlaveContext(di=None, co=None, hr=None, ir=block, zero_mode=True)
    server_context = ModbusServerContext(slaves={1: slave_context}, single=False)
    
    logger.info("Starting Modbus TCP Mimic Server on 0.0.0.0:%d", port)
    StartTcpServer(context=server_context, address=("0.0.0.0", port))
