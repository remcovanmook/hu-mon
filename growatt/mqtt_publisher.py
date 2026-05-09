"""
growatt/mqtt_publisher.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Publishes GrowattReading telemetry to an MQTT broker.

Each field is published to its own topic under a configurable prefix
(default: ``growatt/<serial>/``) so Home Assistant and other consumers
can subscribe to individual measurements without parsing a JSON blob.

A summary JSON payload is also published to ``<prefix>state`` on every
reading, matching the Home Assistant MQTT JSON device pattern.

Requires ``aiomqtt`` (optional dependency):
    pip install aiomqtt
"""

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

# Numeric fields to publish as individual topics in addition to the JSON summary.
_INDIVIDUAL_FIELDS = {
    "pv_total_w", "pv1_w", "pv2_w", "pv3_w", "pv4_w",
    "grid_freq", "meter_total_w",
    "bat_soc", "bat_v", "bat_p",
    "load_p", "eps_p",
    "inverter_temp", "status_code",
    "pv_today_kwh", "pv_total_kwh",
    "grid_import_today_kwh", "grid_export_today_kwh",
    "bat_charge_today_kwh", "bat_discharge_today_kwh",
}


async def run_mqtt_loop(
    store: GrowattStore,
    host: str,
    port: int = 1883,
    user: str = "",
    password: str = "",
    topic_prefix: str = "",
) -> None:
    """
    Async loop: connect to MQTT broker and publish readings as they arrive.

    Publishes two formats on every new reading:
    - ``<prefix>state`` — full JSON summary payload.
    - ``<prefix><field>`` — individual numeric value per field in
      ``_INDIVIDUAL_FIELDS``, as a plain string.

    Reconnects with exponential back-off (2 s → 64 s) on connection loss.

    :param store:        GrowattStore providing latest readings.
    :param host:         MQTT broker hostname or IP.
    :param port:         MQTT broker port (default: 1883).
    :param user:         Optional broker username.
    :param password:     Optional broker password.
    :param topic_prefix: Topic prefix override.  Defaults to
                         ``growatt/<serial>/`` when the first reading
                         is available.
    """
    if not _AIOMQTT_AVAILABLE:
        logger.warning(
            "aiomqtt not installed — MQTT exporter disabled. "
            "Install with: pip install aiomqtt"
        )
        return

    backoff = 2
    last_ts = 0

    while True:
        try:
            logger.info("Connecting to MQTT broker %s:%d", host, port)
            async with aiomqtt.Client(
                hostname=host,
                port=port,
                username=user or None,
                password=password or None,
            ) as client:
                logger.info("MQTT connected to %s:%d", host, port)
                backoff = 2  # reset on successful connect

                while True:
                    r = store.latest_reading()
                    if r and r.ts > last_ts:
                        last_ts = r.ts
                        prefix = topic_prefix or f"growatt/{r.inverter_serial or 'inverter'}/"

                        # Full JSON summary
                        await client.publish(f"{prefix}state", json.dumps(r.to_dict()))

                        # Individual field topics
                        d = r.to_dict()
                        for field in _INDIVIDUAL_FIELDS:
                            val = d.get(field)
                            if val is not None:
                                await client.publish(f"{prefix}{field}", str(val))

                    await asyncio.sleep(2.0)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("MQTT error: %s — reconnecting in %ds", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 64)


def run(
    store: GrowattStore,
    host: str,
    port: int = 1883,
    user: str = "",
    password: str = "",
    topic_prefix: str = "",
) -> None:
    """
    Thread entry point: run the MQTT publish loop synchronously.

    :param store:        GrowattStore providing latest readings.
    :param host:         MQTT broker hostname or IP.
    :param port:         MQTT broker port.
    :param user:         Optional broker username.
    :param password:     Optional broker password.
    :param topic_prefix: Optional topic prefix (e.g. ``home/growatt/``).
    """
    asyncio.run(run_mqtt_loop(store, host, port, user, password, topic_prefix))
