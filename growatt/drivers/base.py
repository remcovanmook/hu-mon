"""
growatt.drivers.base
~~~~~~~~~~~~~~~~~~~~
Abstract base classes and shared data structures for the device driver layer.

Every concrete driver must:
  1. Inherit from BaseDriver (or an intermediate like GrowattBaseDriver).
  2. Implement all abstract methods.
  3. Register itself in growatt.drivers.registry.DRIVER_REGISTRY.

ProbeContext is populated by the shared probe pipeline in registry.py and
passed to every driver's probe() method.  Drivers must not perform additional
Modbus reads inside probe() — they work exclusively with the data already in
the context.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Forward-declared as a string to avoid a circular import; the actual class
# lives in growatt.reading.
from growatt.reading import GrowattReading


@dataclass
class DeviceInfo:
    """
    Static metadata for a discovered device.

    Populated once by driver.read_device_info() at startup and held for the
    duration of the session.  Fields are used to annotate every GrowattReading
    and to tune the poll strategy (e.g. pv_strings determines how many PV
    blocks to parse).
    """
    model: str
    serial: str
    firmware: str
    rated_power_w: int
    bat_nominal_kwh: float
    phases: int              # 1 (single-phase) or 3 (three-phase)
    pv_strings: Optional[int]  # Number of MPPT strings; None if not readable from registers
    has_eps: bool            # True if the device has EPS/backup output
    has_battery: bool        # True if a battery system is confirmed attached


@dataclass
class ProbeContext:
    """
    Results of the shared probe pipeline (registry.py Stages 1–3).

    Carried into every driver's probe() method so no Modbus reads are repeated
    during driver matching.

    Attributes:
        slave_id:       Modbus slave address confirmed to respond.
        supported_fcs:  Set of function codes (3, 4) that responded without
                        error at the confirmed slave_id.
        holding_block:  Registers 0–124 read via FC 03, or None if FC 03 was
                        unavailable or all chunk-size attempts failed.
        max_block_size: Largest register count accepted in a single request
                        during Stage 3.  Stored as a capability tell; drivers
                        may use it to tune their own segment reads.
    """
    slave_id: int
    supported_fcs: set
    holding_block: Optional[list]
    max_block_size: int
    input_block: Optional[list] = field(default=None)
    """Registers 3000–3029 read via FC 04, or None if FC 04 was unavailable.
    Contains inverter-side data (status, PV power) from Protocol II address
    space, which the ShineWifi-X2 bridges correctly unlike FC 03."""

    vpp_dtc: Optional[int] = field(default=None)
    """Device Type Code from VPP holding register 30000 (FC 03), or None if
    the register was unavailable or returned zero.  Used for model metadata
    (series, phases, has_eps) but no longer the primary probe gate."""

    vpp_protocol_version: Optional[int] = field(default=None)
    """VPP Protocol Version from holding register 30099 (FC 03), e.g. 201 for
    V2.01, 202 for V2.02.  A value in [200, 299] is the definitive signal that
    the device supports the VPP register map.  None means the register was
    unavailable or returned an implausible value."""


@dataclass
class ProxyConfig:
    """
    Describes the Modbus address space the proxy server should expose.

    Structured as a nested mapping so the proxy knows exactly which register
    ranges belong to which function code on which slave:

        address_map = {
            slave_id: {
                function_code: [(start_address, count), ...],
                ...
            },
            ...
        }

    Example for a Growatt MOD-HU on slave 1:
        {
            1: {
                4: [(3000, 30), (3030, 80), (3110, 45), (3170, 20), (0, 125)],
            }
        }

    Derived from the selected driver's SEGMENTS constant so the proxy address
    space always matches what the collector actually polls.
    """
    address_map: Dict[int, Dict[int, List[Tuple[int, int]]]]


class BaseDriver(ABC):
    """
    Abstract base class for all device drivers.

    A driver encapsulates everything specific to one device family:
    - How to confirm it is talking to a device it understands (probe).
    - How to read one-time static metadata (read_device_info).
    - How to execute a full telemetry poll cycle (read_registers).
    - Which Modbus address space the proxy server should expose (proxy_config).

    Drivers must be stateless with respect to connection objects.  The Modbus
    client and slave_id are passed explicitly on every call so the same driver
    instance can be tested without a live connection.
    """

    @property
    @abstractmethod
    def driver_id(self) -> str:
        """
        Short, unique identifier for this driver.

        Used in log messages and for --driver CLI override matching.
        Example: 'growatt_mod_hu'.
        """

    @abstractmethod
    def probe(self, ctx: ProbeContext) -> bool:
        """
        Inspect the ProbeContext and return True if this driver recognises
        the attached device.

        Rules:
        - Must never raise — return False on any uncertainty or error.
        - Must not perform additional Modbus reads.
        - Must be fast: all data needed is already in ctx.
        """

    @abstractmethod
    def read_device_info(self, client, slave_id: int) -> DeviceInfo:
        """
        Perform one-time metadata reads and return a populated DeviceInfo.

        Called once after probe() succeeds, before the poll loop starts.
        May raise on read errors — the caller will retry or abort.

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address from ProbeContext.
        """

    @abstractmethod
    def read_registers(self, client, slave_id: int) -> GrowattReading:
        """
        Execute one full telemetry poll cycle and return a GrowattReading.

        Called on every 5-second tick by the collector poll loop.
        Should raise ModbusIOException on any unrecoverable read error so
        the collector can handle reconnection.

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address from ProbeContext.
        """

    @abstractmethod
    def proxy_config(self, slave_id: int) -> ProxyConfig:
        """
        Return the Modbus address space this driver expects the proxy to serve.

        Called once after probe() succeeds, using the confirmed slave_id.
        The proxy server uses this to build its register data block (slave ID,
        supported FCs, address ranges) instead of hardcoding device-specific
        values.

        Implementations should derive ranges directly from their SEGMENTS
        constant so the proxy and the collector stay in sync automatically.

        :param slave_id: Confirmed Modbus slave address from the probe pipeline.
        :returns:        ProxyConfig describing the servable register space.
        """
