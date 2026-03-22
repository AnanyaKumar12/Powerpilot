import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

import asyncpg
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

log = logging.getLogger("anomaly")

MA_WINDOW       = 20
MA_SPIKE_FACTOR = 2.0
ZSCORE_THRESHOLD = 3.0
ZSCORE_WINDOW   = 100
IF_CONTAMINATION = 0.05
IF_MIN_SAMPLES  = 50
STANDBY_POWER_W = 10.0
PF_THRESHOLD    = 0.60
THERMAL_DELTA_C = 5.0


class Severity(str, Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"


class AnomalyType(str, Enum):
    POWER_SPIKE    = "POWER_SPIKE"
    ENERGY_LEAKAGE = "ENERGY_LEAKAGE"
    STANDBY_LOSS   = "STANDBY_LOSS"
    VOLTAGE_ANOMALY = "VOLTAGE_ANOMALY"
    CURRENT_ANOMALY = "CURRENT_ANOMALY"
    THERMAL_TREND  = "THERMAL_TREND"
    PF_DEGRADATION = "PF_DEGRADATION"
    MULTIVARIATE   = "MULTIVARIATE"


@dataclass
class AnomalyAlert:
    ts:           datetime
    device_id:    str
    anomaly_type: AnomalyType
    severity:     Severity
    score:        float
    value:        Optional[float]
    baseline:     Optional[float]
    message:      str
    method:       str
    features:     Dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["ts"]           = self.ts.isoformat()
        d["anomaly_type"] = self.anomaly_type.value
        d["severity"]     = self.severity.value
        return d


async def load_dataframe(pool: asyncpg.Pool, device_id: str,
                         hours: int = 24) -> pd.DataFrame:
    since = datetime.utcnow() - timedelta(hours=hours)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ts, voltage, current, power, energy_kwh,
                      frequency, power_factor, temperature
               FROM telemetry
               WHERE device_id=$1 AND ts >= $2
                 AND voltage IS NOT NULL AND current IS NOT NULL
               ORDER BY ts ASC""",
            device_id, since,
        )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    for col in ["voltage", "current", "power", "energy_kwh",
                "frequency", "power_factor", "temperature"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["voltage", "current", "power"])


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["voltage", "current", "power", "temperature"]:
        rm = df[col].rolling(ZSCORE_WINDOW, min_periods=5).mean()
        rs = df[col].rolling(ZSCORE_WINDOW, min_periods=5).std()
        df[f"{col}_rm"] = rm
        df[f"{col}_rs"] = rs
        df[f"{col}_z"]  = ((df[col] - rm) / rs.replace(0, np.nan)).fillna(0)
        df[f"{col}_ma"] = df[col].rolling(MA_WINDOW, min_periods=3).mean()
    df["power_roc"]   = df["power"].diff().abs()
    df["voltage_roc"] = df["voltage"].diff().abs()
    df["temp_roc"]    = df["temperature"].diff()
    return df


def detect_isolation_forest(df: pd.DataFrame,
                             device_id: str) -> List[AnomalyAlert]:
    if len(df) < IF_MIN_SAMPLES:
        log.info(f"[IF] Skipped - only {len(df)} rows, need {IF_MIN_SAMPLES}")
        return []

    feat_cols = [c for c in
                 ["voltage", "current", "power", "power_factor",
                  "voltage_z", "current_z", "power_z",
                  "power_roc", "voltage_roc"]
                 if c in df.columns]

    X      = df[feat_cols].fillna(0).values
    X_sc   = StandardScaler().fit_transform(X)
    model  = IsolationForest(n_estimators=100,
                              contamination=IF_CONTAMINATION,
                              random_state=42)
    labels = model.fit_predict(X_sc)
    scores = model.decision_function(X_sc)

    alerts = []
    for idx in np.where(labels == -1)[0]:
        row   = df.iloc[idx]
        score = abs(float(scores[idx]))
        sev   = Severity.CRITICAL if score > 0.2 else Severity.WARNING

        alerts.append(AnomalyAlert(
            ts           = row.name.to_pydatetime(),
            device_id    = device_id,
            anomaly_type = AnomalyType.MULTIVARIATE,
            severity     = sev,
            score        = round(score, 4),
            value        = round(float(row["power"]), 2),
            baseline     = round(float(row.get("power_ma") or 0), 2),
            message      = (f"Multi-feature anomaly (score={score:.4f}) "
                            f"V={row['voltage']:.1f}V "
                            f"I={row['current']:.3f}A "
                            f"P={row['power']:.1f}W"),
            method       = "IsolationForest",
            features     = {
                "voltage":      round(float(row["voltage"]),      2),
                "current":      round(float(row["current"]),      3),
                "power":        round(float(row["power"]),        2),
                "power_factor": round(float(row["power_factor"]), 3),
            },
        ))

    log.info(f"[IF] {len(alerts)} anomalies / {len(df)} records")
    return alerts


def detect_zscore(df: pd.DataFrame, device_id: str) -> List[AnomalyAlert]:
    checks = [
        ("power",   AnomalyType.POWER_SPIKE,     Severity.WARNING, "Power anomaly"),
        ("voltage", AnomalyType.VOLTAGE_ANOMALY,  Severity.WARNING, "Voltage anomaly"),
        ("current", AnomalyType.CURRENT_ANOMALY,  Severity.WARNING, "Current anomaly"),
    ]
    alerts = []
    for col, atype, base_sev, label in checks:
        zcol = f"{col}_z"
        if zcol not in df.columns:
            continue
        for ts, row in df[df[zcol].abs() > ZSCORE_THRESHOLD].iterrows():
            z   = abs(float(row[zcol]))
            sev = Severity.CRITICAL if z > 5.0 else base_sev
            alerts.append(AnomalyAlert(
                ts           = ts.to_pydatetime(),
                device_id    = device_id,
                anomaly_type = atype,
                severity     = sev,
                score        = round(z, 3),
                value        = round(float(row[col]), 3),
                baseline     = round(float(row.get(f"{col}_rm") or 0), 3),
                message      = (f"{label}: {col}={row[col]:.3f} "
                                f"(z={z:.2f}, mean={row.get(f'{col}_rm', 0):.3f})"),
                method       = "ZScore",
                features     = {"z_score": round(z, 3)},
            ))

    log.info(f"[ZScore] {len(alerts)} anomalies")
    return alerts


def detect_power_spikes(df: pd.DataFrame, device_id: str) -> List[AnomalyAlert]:
    if "power_ma" not in df.columns:
        return []
    threshold = df["power_ma"] * MA_SPIKE_FACTOR
    alerts    = []
    for ts, row in df[df["power"] > threshold].iterrows():
        ratio = float(row["power"]) / (float(row["power_ma"]) + 0.01)
        alerts.append(AnomalyAlert(
            ts           = ts.to_pydatetime(),
            device_id    = device_id,
            anomaly_type = AnomalyType.POWER_SPIKE,
            severity     = Severity.CRITICAL if ratio > 3 else Severity.WARNING,
            score        = round(ratio, 3),
            value        = round(float(row["power"]),    2),
            baseline     = round(float(row["power_ma"]), 2),
            message      = (f"Power spike: {row['power']:.1f}W "
                            f"vs MA={row['power_ma']:.1f}W ({ratio:.1f}x)"),
            method       = "MovingAverage",
            features     = {"ratio": round(ratio, 3)},
        ))
    return alerts


def detect_standby_loss(df: pd.DataFrame, device_id: str) -> List[AnomalyAlert]:
    standby = df[
        (df["current"] > 0.3) &
        (df["current"] < 1.0) &
        (df["power"]   > STANDBY_POWER_W)
    ]
    if len(standby) < 10:
        return []

    avg_p     = float(standby["power"].mean())
    daily_kwh = avg_p / 1000 * 24
    return [AnomalyAlert(
        ts           = datetime.utcnow(),
        device_id    = device_id,
        anomaly_type = AnomalyType.STANDBY_LOSS,
        severity     = Severity.WARNING,
        score        = round(avg_p / STANDBY_POWER_W, 2),
        value        = round(avg_p, 2),
        baseline     = STANDBY_POWER_W,
        message      = (f"Standby waste: avg={avg_p:.1f}W "
                        f"over {len(standby)} samples. "
                        f"Est. daily waste: {daily_kwh:.3f} kWh"),
        method       = "DomainKnowledge",
        features     = {"standby_samples": len(standby),
                        "daily_kwh_waste": round(daily_kwh, 3)},
    )]


def detect_thermal_trend(df: pd.DataFrame, device_id: str) -> List[AnomalyAlert]:
    if "temperature" not in df.columns:
        return []
    recent = df["temperature"].dropna().tail(30)
    if len(recent) < 5:
        return []

    delta = float(recent.max() - recent.min())
    slope = float(np.polyfit(range(len(recent)), recent.values, 1)[0])
    if delta < THERMAL_DELTA_C or slope <= 0.1:
        return []

    t_now = float(recent.iloc[-1])
    return [AnomalyAlert(
        ts           = datetime.utcnow(),
        device_id    = device_id,
        anomaly_type = AnomalyType.THERMAL_TREND,
        severity     = Severity.CRITICAL if t_now > 65 else Severity.WARNING,
        score        = round(slope, 4),
        value        = round(t_now, 1),
        baseline     = round(float(recent.iloc[0]), 1),
        message      = (f"Rising temperature: {recent.iloc[0]:.1f}C -> {t_now:.1f}C "
                        f"(+{delta:.1f}C, slope={slope:.3f}C/sample)"),
        method       = "ThermalAnalysis",
        features     = {"slope": round(slope, 4), "delta_c": round(delta, 2)},
    )]


def detect_pf_degradation(df: pd.DataFrame, device_id: str) -> List[AnomalyAlert]:
    bad = df[(df["power_factor"] < PF_THRESHOLD) & (df["current"] > 0.5)]
    if len(bad) < 5:
        return []
    avg_pf = float(bad["power_factor"].mean())
    return [AnomalyAlert(
        ts           = datetime.utcnow(),
        device_id    = device_id,
        anomaly_type = AnomalyType.PF_DEGRADATION,
        severity     = Severity.WARNING,
        score        = round(1.0 - avg_pf, 3),
        value        = round(avg_pf, 3),
        baseline     = PF_THRESHOLD,
        message      = (f"PF degradation: avg PF={avg_pf:.3f} "
                        f"below {PF_THRESHOLD} in {len(bad)} samples"),
        method       = "DomainKnowledge",
        features     = {"low_pf_samples": len(bad), "avg_pf": round(avg_pf, 3)},
    )]


def deduplicate(alerts: List[AnomalyAlert]) -> List[AnomalyAlert]:
    seen   = {}
    result = []
    sev_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    for a in sorted(alerts, key=lambda x: sev_order.get(x.severity, 3)):
        bucket = (
            a.anomaly_type,
            a.ts.replace(second=0, microsecond=0).replace(
                minute=(a.ts.minute // 5) * 5
            ),
        )
        if bucket not in seen:
            seen[bucket] = True
            result.append(a)
    return result


async def run_all(pool: asyncpg.Pool, device_id: str,
                  hours: int = 24) -> List[AnomalyAlert]:
    df = await load_dataframe(pool, device_id, hours)
    if df.empty:
        log.warning(f"[anomaly] No data for {device_id}")
        return []

    df = add_features(df)

    raw: List[AnomalyAlert] = []
    raw += detect_isolation_forest(df, device_id)
    raw += detect_zscore(df, device_id)
    raw += detect_power_spikes(df, device_id)
    raw += detect_standby_loss(df, device_id)
    raw += detect_thermal_trend(df, device_id)
    raw += detect_pf_degradation(df, device_id)

    alerts = deduplicate(raw)

    sev_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    alerts.sort(key=lambda a: (sev_order.get(a.severity, 3), -a.score))

    log.info(f"[anomaly] {len(alerts)} alerts for {device_id} "
             f"({hours}h, {len(df)} records)")
    return alerts
