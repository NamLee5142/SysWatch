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

    @classmethod
    def from_record(cls, record) -> "Snapshot":
        """Rebuild the agent's nested shape from a flat stored row.

        Takes the record structurally rather than importing SnapshotRecord, so
        the API models stay independent of the database layer.
        """
        return cls(
            collectedAt=record.collected_at,
            cpuInfo=CPUInfo(
                coreCount=record.cpu_core_count,
                usagePercent=record.cpu_usage_percent,
            ),
            memoryInfo=MemoryInfo(
                totalMB=record.mem_total_mb,
                usedMB=record.mem_used_mb,
            ),
            diskInfo=DiskInfo(
                totalGB=record.disk_total_gb,
                freeGB=record.disk_free_gb,
            ),
            systemInfo=SystemInfo(
                name=record.os_name,
                version=record.os_version,
                hostName=record.host_name,
            ),
        )


class SnapshotPage(BaseModel):
    """A page of stored snapshots, newest first."""

    items: list[Snapshot]
    # Total rows matching the filters, ignoring limit and offset, so a caller
    # can tell whether more pages exist without fetching them.
    count: int
