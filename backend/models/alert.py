from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class AlertRow(BaseModel):
    id:           int
    ts:           datetime
    device_id:    str
    alert_type:   str
    severity:     str
    value:        Optional[float] = None
    threshold:    Optional[float] = None
    message:      Optional[str]   = None
    acknowledged: bool = False


class AlertAcknowledge(BaseModel):
    alert_ids: List[int]


class AlertStats(BaseModel):
    alert_type: str
    severity:   str
    count:      int
