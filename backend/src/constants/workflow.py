from enum import StrEnum


class Role(StrEnum):
    OPERATOR = 'operator'
    REVIEWER = 'reviewer'
    VIEWER = 'viewer'


class Status(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETE = 'complete'
    FAILED = 'failed'


class EvidenceState(StrEnum):
    VALID = 'valid'
    VOID = 'void'


class HandoverStatus(StrEnum):
    AVAILABLE = 'available'
    HANDED_OVER = 'handed_over'
    PENDING_RECOVERY = 'pending_recovery'
    RECOVERED = 'recovered'
