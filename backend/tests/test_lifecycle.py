"""Tests for instance lifecycle state machine and spec validation."""

import pytest

from app.core.lifecycle import (
    InstanceState,
    can_transition,
    get_action_transition,
    validate_instance_specs,
    validate_transition,
)

# --- State Machine -----------------------------------------------------


class TestStateTransitions:
    def test_valid_transitions(self):
        assert can_transition("pending", "creating")
        assert can_transition("creating", "running")
        assert can_transition("running", "stopping")
        assert can_transition("stopping", "stopped")
        assert can_transition("stopped", "starting")
        assert can_transition("starting", "running")
        assert can_transition("running", "terminating")
        assert can_transition("terminating", "terminated")

    def test_invalid_transitions(self):
        assert not can_transition("pending", "running")  # must go through creating
        assert not can_transition("stopped", "stopped")  # self-transition
        assert not can_transition("terminated", "running")  # terminal state
        assert not can_transition("creating", "stopped")  # must go through running

    def test_error_transitions(self):
        # Any state can transition to error
        for state in InstanceState:
            if state in (InstanceState.TERMINATED, InstanceState.ERROR):
                continue
            assert can_transition(state.value, "error"), f"{state} should be able to transition to error"

    def test_error_recovery(self):
        assert can_transition("error", "starting")
        assert can_transition("error", "terminating")
        assert not can_transition("error", "running")  # must go through starting

    def test_validate_transition_raises(self):
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition("stopped", "running")

    def test_unknown_state(self):
        assert not can_transition("unknown", "running")
        assert not can_transition("running", "unknown")


# --- Action Transitions ------------------------------------------------


class TestActionTransitions:
    def test_start_from_stopped(self):
        assert get_action_transition("start", "stopped") == InstanceState.STARTING

    def test_start_from_error(self):
        assert get_action_transition("start", "error") == InstanceState.STARTING

    def test_stop_from_running(self):
        assert get_action_transition("stop", "running") == InstanceState.STOPPING

    def test_reboot_from_running(self):
        assert get_action_transition("reboot", "running") == InstanceState.REBOOTING

    def test_suspend_from_running(self):
        assert get_action_transition("suspend", "running") == InstanceState.SUSPENDING

    def test_resume_from_suspended(self):
        assert get_action_transition("resume", "suspended") == InstanceState.RESUMING

    def test_terminate_from_multiple_states(self):
        assert get_action_transition("terminate", "stopped") == InstanceState.TERMINATING
        assert get_action_transition("terminate", "suspended") == InstanceState.TERMINATING
        assert get_action_transition("terminate", "running") == InstanceState.TERMINATING
        assert get_action_transition("terminate", "error") == InstanceState.TERMINATING

    def test_invalid_action_state(self):
        with pytest.raises(ValueError, match="Cannot stop"):
            get_action_transition("stop", "stopped")

    def test_unknown_action(self):
        with pytest.raises(ValueError, match="Unknown action"):
            get_action_transition("fly", "running")

    def test_unknown_state(self):
        with pytest.raises(ValueError, match="Unknown state"):
            get_action_transition("start", "flying")


# --- Spec Validation --------------------------------------------------


class TestSpecValidation:
    def test_valid_specs(self):
        errors = validate_instance_specs(vcpus=2, ram_mib=2048, disk_gib=40)
        assert errors == []

    def test_invalid_vcpus(self):
        errors = validate_instance_specs(vcpus=0, ram_mib=1024, disk_gib=10)
        assert len(errors) == 1
        assert errors[0].field == "vcpus"

    def test_vcpus_too_high(self):
        errors = validate_instance_specs(vcpus=256, ram_mib=1024, disk_gib=10)
        assert len(errors) == 1
        assert errors[0].field == "vcpus"

    def test_ram_not_multiple_of_128(self):
        errors = validate_instance_specs(vcpus=1, ram_mib=1000, disk_gib=10)
        assert len(errors) == 1
        assert errors[0].field == "ram_mib"
        assert "multiple of 128" in errors[0].message

    def test_ram_too_low(self):
        errors = validate_instance_specs(vcpus=1, ram_mib=64, disk_gib=10)
        assert len(errors) == 1
        assert errors[0].field == "ram_mib"

    def test_disk_zero(self):
        errors = validate_instance_specs(vcpus=1, ram_mib=512, disk_gib=0)
        assert len(errors) == 1
        assert errors[0].field == "disk_gib"

    def test_disk_too_large(self):
        errors = validate_instance_specs(vcpus=1, ram_mib=512, disk_gib=99999)
        assert len(errors) == 1
        assert errors[0].field == "disk_gib"

    def test_multiple_errors(self):
        errors = validate_instance_specs(vcpus=0, ram_mib=100, disk_gib=0)
        assert len(errors) == 3

    def test_custom_limits(self):
        errors = validate_instance_specs(vcpus=4, ram_mib=2048, disk_gib=40, max_vcpus=2)
        assert len(errors) == 1
        assert errors[0].field == "vcpus"

    def test_boundary_values(self):
        # Exactly at boundaries
        assert validate_instance_specs(vcpus=1, ram_mib=128, disk_gib=1) == []
        assert validate_instance_specs(vcpus=128, ram_mib=524288, disk_gib=10000) == []
