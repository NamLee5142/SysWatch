from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

Metric = Literal["cpu", "memory", "disk"]
Bucket = Literal["raw", "minute", "hour", "day"]


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


class ProcessEntry(BaseModel):
    pid: int
    name: str
    memoryMB: int


class ProcessInfo(BaseModel):
    # Total running processes, from the agent's full process walk — not the
    # length of `top`, which is only the heaviest few.
    count: int
    top: list[ProcessEntry]


class NetworkInterface(BaseModel):
    name: str
    # Cumulative octet counters straight from the adapter.
    bytesSent: int
    bytesRecv: int
    # Per-second rates the agent derives from the delta between its own samples.
    bytesSentPerSec: float
    bytesRecvPerSec: float


class NetworkInfo(BaseModel):
    interfaces: list[NetworkInterface]


class Snapshot(BaseModel):
    # Stamped by the agent when the metrics were collected, not when the backend
    # fetched them. Serialized as ISO-8601 UTC, e.g. 2026-08-12T11:15:27Z.
    collectedAt: datetime
    cpuInfo: CPUInfo
    memoryInfo: MemoryInfo
    diskInfo: DiskInfo
    systemInfo: SystemInfo
    # Optional for one release: an agent built before Sprint 7 sends neither
    # block, and rejecting its payload would turn every poll into a 502. The
    # same compatibility window collectedAt had in Sprint 5.
    processInfo: Optional[ProcessInfo] = None
    networkInfo: Optional[NetworkInfo] = None

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


class SeriesPoint(BaseModel):
    """One point on a chart: the bucket's start time and its average value."""

    t: datetime
    # Always a percentage, so cpu, memory and disk share one 0-100 axis and one
    # chart component can render any of them.
    value: float

    @classmethod
    def from_point(cls, point) -> "SeriesPoint":
        return cls(t=point.at, value=point.value)


class Series(BaseModel):
    """A metric over time, oldest first.

    Note the order: /snapshots is newest-first for paging, this is oldest-first
    because a chart is read left to right. Reversing one silently flips an axis.
    """

    metric: Metric
    bucket: Bucket
    points: list[SeriesPoint]
