import time
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Any

@dataclass
class GrowattReading:
    ts: int = field(default_factory=lambda: int(time.time() * 1000))
    status_code: int = 0
    serial: str = "default"
    
    # PV / Solar Array
    pv_total_w: float = 0.0
    pv1_v: float = 0.0
    pv1_a: float = 0.0
    pv1_w: float = 0.0
    pv2_v: float = 0.0
    pv2_a: float = 0.0
    pv2_w: float = 0.0
    pv3_v: float = 0.0
    pv3_a: float = 0.0
    pv3_w: float = 0.0
    pv4_v: float = 0.0
    pv4_a: float = 0.0
    pv4_w: float = 0.0
    
    # Grid / AC Side
    grid_l1_v: float = 0.0
    grid_l1_a: float = 0.0
    grid_l2_v: float = 0.0
    grid_l2_a: float = 0.0
    grid_l3_v: float = 0.0
    grid_l3_a: float = 0.0
    grid_freq: float = 0.0
    meter_total_w: float = 0.0  # pos: export, neg: import
    meter_l1_w: float = 0.0
    meter_l2_w: float = 0.0
    meter_l3_w: float = 0.0

    # Battery & Load
    bat_soc: float = 0.0
    bat_v: float = 0.0
    bat_i: float = 0.0
    bat_p: float = 0.0  # pos: charge, neg: discharge
    bat_nominal_kwh: float = 0.0  # Nominal battery capacity
    load_p: float = 0.0
    eps_p: float = 0.0
    
    # Energy Counters
    pv_today_kwh: float = 0.0
    pv_total_kwh: float = 0.0
    grid_import_today_kwh: float = 0.0
    grid_export_today_kwh: float = 0.0
    load_today_kwh: float = 0.0
    bat_charge_today_kwh: float = 0.0
    bat_discharge_today_kwh: float = 0.0

    # Metadata
    inverter_model: str = ""
    inverter_serial: str = ""
    inverter_firmware: str = ""

    
    # Raw payload cache for the Proxy
    raw_payload: bytes = b''

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Exclude raw payload from JSON representation
        d.pop('raw_payload', None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GrowattReading":
        safe_data = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**safe_data)
