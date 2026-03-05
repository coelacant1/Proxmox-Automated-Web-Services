"""Instance lifecycle state machine and spec validation utilities."""

import enum


class InstanceState(enum.StrEnum):
    """Valid states for a VM or container instance."""

    PENDING = "pending"
    CREATING = "creating"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    STARTING = "starting"
    REBOOTING = "rebooting"
    SUSPENDING = "suspending"
    SUSPENDED = "suspended"
    RESUMING = "resuming"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    ERROR = "error"


# Valid state transitions: from_state -> set of valid to_states
VALID_TRANSITIONS: dict[InstanceState, set[InstanceState]] = {
    InstanceState.PENDING: {InstanceState.CREATING, InstanceState.ERROR},
    InstanceState.CREATING: {InstanceState.RUNNING, InstanceState.ERROR},
    InstanceState.RUNNING: {
        InstanceState.STOPPING,
        InstanceState.REBOOTING,
        InstanceState.SUSPENDING,
        InstanceState.TERMINATING,
        InstanceState.ERROR,
    },
    InstanceState.STOPPING: {InstanceState.STOPPED, InstanceState.ERROR},
    InstanceState.STOPPED: {InstanceState.STARTING, InstanceState.TERMINATING, InstanceState.ERROR},
    InstanceState.STARTING: {InstanceState.RUNNING, InstanceState.ERROR},
    InstanceState.REBOOTING: {InstanceState.RUNNING, InstanceState.ERROR},
    InstanceState.SUSPENDING: {InstanceState.SUSPENDED, InstanceState.ERROR},
    InstanceState.SUSPENDED: {InstanceState.RESUMING, InstanceState.TERMINATING, InstanceState.ERROR},
    InstanceState.RESUMING: {InstanceState.RUNNING, InstanceState.ERROR},
    InstanceState.TERMINATING: {InstanceState.TERMINATED, InstanceState.ERROR},
    InstanceState.TERMINATED: set(),  # terminal state
    InstanceState.ERROR: {InstanceState.STARTING, InstanceState.TERMINATING},
}


def can_transition(current: str, target: str) -> bool:
    """Check if a state transition is valid."""
    try:
        current_state = InstanceState(current)
        target_state = InstanceState(target)
    except ValueError:
        return False
    return target_state in VALID_TRANSITIONS.get(current_state, set())


def validate_transition(current: str, target: str) -> None:
    """Validate a state transition, raising ValueError if invalid."""
    if not can_transition(current, target):
        raise ValueError(f"Invalid state transition: {current} -> {target}")


# User-initiated actions and the transitions they trigger
ACTION_TRANSITIONS: dict[str, tuple[InstanceState, InstanceState]] = {
    "start": (InstanceState.STOPPED, InstanceState.STARTING),
    "stop": (InstanceState.RUNNING, InstanceState.STOPPING),
    "reboot": (InstanceState.RUNNING, InstanceState.REBOOTING),
    "suspend": (InstanceState.RUNNING, InstanceState.SUSPENDING),
    "resume": (InstanceState.SUSPENDED, InstanceState.RESUMING),
    "terminate": (InstanceState.STOPPED, InstanceState.TERMINATING),
}

# Some actions can be initiated from multiple states
MULTI_SOURCE_ACTIONS: dict[str, dict[InstanceState, InstanceState]] = {
    "terminate": {
        InstanceState.STOPPED: InstanceState.TERMINATING,
        InstanceState.SUSPENDED: InstanceState.TERMINATING,
        InstanceState.RUNNING: InstanceState.TERMINATING,
        InstanceState.ERROR: InstanceState.TERMINATING,
    },
    "start": {
        InstanceState.STOPPED: InstanceState.STARTING,
        InstanceState.ERROR: InstanceState.STARTING,
    },
}


def get_action_transition(action: str, current_state: str) -> InstanceState:
    """Get the target state for a user action from the current state."""
    try:
        current = InstanceState(current_state)
    except ValueError:
        raise ValueError(f"Unknown state: {current_state}")

    # Check multi-source actions first
    if action in MULTI_SOURCE_ACTIONS:
        target = MULTI_SOURCE_ACTIONS[action].get(current)
        if target:
            return target
        valid_sources = list(MULTI_SOURCE_ACTIONS[action].keys())
        raise ValueError(f"Cannot {action} from state {current_state}. Valid states: {valid_sources}")

    if action not in ACTION_TRANSITIONS:
        raise ValueError(f"Unknown action: {action}")

    required_state, target_state = ACTION_TRANSITIONS[action]
    if current != required_state:
        raise ValueError(f"Cannot {action} from state {current_state}. Must be in {required_state.value}")
    return target_state


# --- Spec Validation -----------------------------------------------------


class SpecError:
    """A spec validation error."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def __repr__(self) -> str:
        return f"SpecError({self.field}: {self.message})"


def validate_instance_specs(
    vcpus: int,
    ram_mib: int,
    disk_gib: int,
    max_vcpus: int = 128,
    max_ram_mib: int = 524288,
    max_disk_gib: int = 10000,
) -> list[SpecError]:
    """Validate instance specifications. Returns list of errors (empty = valid)."""
    errors: list[SpecError] = []

    # CPU: positive integer
    if not isinstance(vcpus, int) or vcpus < 1:
        errors.append(SpecError("vcpus", "Must be a positive integer"))
    elif vcpus > max_vcpus:
        errors.append(SpecError("vcpus", f"Maximum is {max_vcpus} vCPUs"))

    # RAM: positive integer, multiple of 128 MiB
    if not isinstance(ram_mib, int) or ram_mib < 128:
        errors.append(SpecError("ram_mib", "Must be at least 128 MiB"))
    elif ram_mib % 128 != 0:
        errors.append(SpecError("ram_mib", "Must be a multiple of 128 MiB"))
    elif ram_mib > max_ram_mib:
        errors.append(SpecError("ram_mib", f"Maximum is {max_ram_mib} MiB"))

    # Disk: positive integer (whole GiB)
    if not isinstance(disk_gib, int) or disk_gib < 1:
        errors.append(SpecError("disk_gib", "Must be at least 1 GiB"))
    elif disk_gib > max_disk_gib:
        errors.append(SpecError("disk_gib", f"Maximum is {max_disk_gib} GiB"))

    return errors
