from datetime import datetime

from pydantic import BaseModel


class CPUInfo(BaseModel):
    coreCount: int
    usagePercent: float


class MemoryInfo(BaseModel):
    totalMB: int
    usedMB: int


class DiskInfo(BaseModel):
    totalGB: int
    freeGB: int


class SystemInfo(BaseModel):
    name: str
    version: str
    hostName: str


class Snapshot(BaseModel):
    # Stamped by the agent when the metrics were collected, not when the backend
    # fetched them. Serialized as ISO-8601 UTC, e.g. 2026-08-12T11:15:27Z.
    collectedAt: datetime
    cpuInfo: CPUInfo
    memoryInfo: MemoryInfo
    diskInfo: DiskInfo
    systemInfo: SystemInfo

    @classmethod
    def from_payload(cls, payload: dict) -> "Snapshot":
        return cls(**payload)
