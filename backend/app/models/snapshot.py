from typing import Optional

from pydantic import BaseModel, Field


class CPUInfo(BaseModel):
    coreCount: int = Field(..., alias="coreCount")
    usagePercent: float = Field(..., alias="usagePercent")


class MemoryInfo(BaseModel):
    totalMB: int = Field(..., alias="totalMB")
    usedMB: int = Field(..., alias="usedMB")


class DiskInfo(BaseModel):
    totalGB: int = Field(..., alias="totalGB")
    freeGB: int = Field(..., alias="freeGB")


class SystemInfo(BaseModel):
    name: str = Field(..., alias="name")
    version: str = Field(..., alias="version")
    hostName: str = Field(..., alias="hostName")


class Snapshot(BaseModel):
    cpuInfo: CPUInfo
    memoryInfo: MemoryInfo
    diskInfo: DiskInfo
    systemInfo: SystemInfo

    @classmethod
    def from_payload(cls, payload: dict) -> "Snapshot":
        return cls(**payload)


class SnapshotEnvelope(BaseModel):
    snapshot: Optional[Snapshot] = None
