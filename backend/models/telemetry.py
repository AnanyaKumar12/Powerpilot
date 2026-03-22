from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class TelemetryRow(BaseModel):
    ts:             datetime
    device_id:      str
    voltage:        Optional[float] = None
    current:        Optional[float] = None
    power:          Optional[float] = None
    energy_kwh:     Optional[float] = None
    frequency:      Optional[float] = None
    power_factor:   Optional[float] = None
    temperature:    Optional[float] = None
    apparent_power: Optional[float] = None
    wifi_rssi:      Optional[int]   = None


class RealTimeData(BaseModel):
    device_id:      str
    ts:             datetime
    voltage:        Optional[float] = None
    current:        Optional[float] = None
    power:          Optional[float] = None
    energy_kwh:     Optional[float] = None
    frequency:      Optional[float] = None
    power_factor:   Optional[float] = None
    temperature:    Optional[float] = None
    apparent_power: Optional[float] = None
    status:         str
    active_faults:  List[str] = []


class HistoryResponse(BaseModel):
    device_id: str
    from_ts:   str
    count:     int
    data:      List[TelemetryRow]


class SummaryStats(BaseModel):
    device_id:    str
    from_ts:      datetime
    to_ts:        datetime
    avg_voltage:  Optional[float] = None
    avg_current:  Optional[float] = None
    avg_power:    Optional[float] = None
    max_power:    Optional[float] = None
    total_energy: Optional[float] = None
    avg_pf:       Optional[float] = None
    fault_count:  int = 0
    records:      int = 0
