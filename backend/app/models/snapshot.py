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
    cpuInfo: CPUInfo
    memoryInfo: MemoryInfo
    diskInfo: DiskInfo
    systemInfo: SystemInfo

    @classmethod
    def from_payload(cls, payload: dict) -> "Snapshot":
        return cls(**payload)
