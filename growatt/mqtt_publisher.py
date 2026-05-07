import asyncio
import json
import logging
import time

from growatt.store import GrowattStore

logger = logging.getLogger("growatt_mqtt")

try:
    import aiomqtt
    _AIOMQTT_AVAILABLE = True
except ImportError:
    _AIOMQTT_AVAILABLE = False

async def run_mqtt_loop(store: GrowattStore, host: str, port: int = 1883, user: str = "", password: str = ""):
    if not _AIOMQTT_AVAILABLE:
        logger.warning("aiomqtt not installed. MQTT exporter disabled. Install with: pip install aiomqtt")
        return

    logger.info("Connecting to MQTT broker %s:%d", host, port)
    client = aiomqtt.Client(hostname=host, port=port, username=user or None, password=password or None)
    
    last_ts = 0
    try:
        async with client:
            logger.info("MQTT connected. Publishing to 'growatt/sensor/state'")
            while True:
                r = store.latest_reading()
                if r and r.ts > last_ts:
                    last_ts = r.ts
                    payload = json.dumps(r.to_dict())
                    await client.publish("growatt/sensor/state", payload)
                await asyncio.sleep(2.0)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("MQTT Error: %s", e)

def run(store: GrowattStore, host: str, port: int = 1883, user: str = "", password: str = ""):
    asyncio.run(run_mqtt_loop(store, host, port, user, password))
