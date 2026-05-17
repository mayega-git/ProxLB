"""
Unit tests for DiskIgnoreFilter.

DiskIgnoreFilter flags guests whose disk footprint exceeds a configured
threshold so that the rest of the balancing pipeline skips them. The tests
cover both ``assigned`` and ``used`` modes, unit conversion, the
short-circuit branches (disabled / no threshold), and the integration with
Calculations.relocate_guests where ignored guests must not be migrated.
"""

__author__ = "Florian Paul Azim Hoberg <gyptazy>"
__copyright__ = "Copyright (C) 2026 Florian Paul Azim Hoberg (@gyptazy)"
__license__ = "GPL-3.0"


from proxlb.models.calculations import Calculations
from proxlb.models.disk_ignore_filter import DiskIgnoreFilter
from proxlb.utils.config_parser import Config
from proxlb.utils.proxlb_data import ProxLbData


GB = 1024 ** 3
BalancingResource = Config.Balancing.Resource


def _make_guest(
    name: str,
    disk_total_gb: float,
    disk_used_gb: float,
    guest_id: int = 100,
    ignore: bool = False,
    node_current: str = "node1",
) -> ProxLbData.Guest:
    disk = ProxLbData.Guest.Metric(
        total=int(disk_total_gb * GB),
        used=disk_used_gb * GB,
        pressure_some_percent=0.0,
        pressure_full_percent=0.0,
        pressure_some_spikes_percent=0.0,
        pressure_full_spikes_percent=0.0,
        pressure_hot=False,
    )
    cpu = ProxLbData.Guest.Metric(
        total=1, used=0.1,
        pressure_some_percent=0.0, pressure_full_percent=0.0,
        pressure_some_spikes_percent=0.0, pressure_full_spikes_percent=0.0,
        pressure_hot=False,
    )
    mem = ProxLbData.Guest.Metric(
        total=GB, used=0.5 * GB,
        pressure_some_percent=0.0, pressure_full_percent=0.0,
        pressure_some_spikes_percent=0.0, pressure_full_spikes_percent=0.0,
        pressure_hot=False,
    )
    return ProxLbData.Guest(
        name=name,
        id=guest_id,
        node_current=node_current,
        node_target=node_current,
        processed=False,
        pressure_hot=False,
        tags=[],
        pools=[],
        ha_rules=[],
        affinity_groups=[name],
        anti_affinity_groups=[],
        ignore=ignore,
        node_relationships=[],
        node_relationships_strict=False,
        type=Config.GuestType.Vm,
        cpu=cpu,
        memory=mem,
        disk=disk,
    )


def _make_balancing(
    enable: bool = True,
    threshold: int | None = 500,
    mode: str = "assigned",
) -> Config.Balancing:
    return Config.Balancing(
        disk_ignore_enable=enable,
        disk_ignore_threshold=threshold,
        disk_ignore_mode=mode,  # type: ignore[arg-type]
    )


def test_disabled_does_nothing() -> None:
    """When disk_ignore_enable is False the filter must not touch any guest."""
    guests = {"vm1": _make_guest("vm1", disk_total_gb=1000, disk_used_gb=900)}
    balancing = _make_balancing(enable=False, threshold=500)

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == []
    assert guests["vm1"].ignore is False


def test_threshold_none_does_nothing() -> None:
    """An enabled filter without a threshold must be a no-op."""
    guests = {"vm1": _make_guest("vm1", disk_total_gb=1000, disk_used_gb=900)}
    balancing = _make_balancing(enable=True, threshold=None)

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == []
    assert guests["vm1"].ignore is False


def test_above_threshold_assigned_flags_guest() -> None:
    """In ``assigned`` mode, disk.total above the threshold must be flagged."""
    guests = {"vm1": _make_guest("vm1", disk_total_gb=600, disk_used_gb=10)}
    balancing = _make_balancing(threshold=500, mode="assigned")

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == [(100, "vm1")]
    assert guests["vm1"].ignore is True


def test_above_threshold_used_flags_guest() -> None:
    """In ``used`` mode, disk.used above the threshold must be flagged."""
    guests = {"vm1": _make_guest("vm1", disk_total_gb=1000, disk_used_gb=600)}
    balancing = _make_balancing(threshold=500, mode="used")

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == [(100, "vm1")]
    assert guests["vm1"].ignore is True


def test_assigned_mode_ignores_used_value() -> None:
    """Assigned mode must look at disk.total — not disk.used."""
    # used is huge but assigned is below threshold → must NOT be flagged
    guests = {"vm1": _make_guest("vm1", disk_total_gb=100, disk_used_gb=900)}
    balancing = _make_balancing(threshold=500, mode="assigned")

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == []
    assert guests["vm1"].ignore is False


def test_below_threshold_is_left_alone() -> None:
    """A guest under the threshold must not be flagged."""
    guests = {"vm1": _make_guest("vm1", disk_total_gb=100, disk_used_gb=50)}
    balancing = _make_balancing(threshold=500)

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == []
    assert guests["vm1"].ignore is False


def test_equal_to_threshold_is_left_alone() -> None:
    """Comparison is strictly greater-than: equality does not trigger."""
    guests = {"vm1": _make_guest("vm1", disk_total_gb=500, disk_used_gb=10)}
    balancing = _make_balancing(threshold=500)

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == []
    assert guests["vm1"].ignore is False


def test_already_ignored_guest_skipped() -> None:
    """Guests already ignored (e.g. via plb_ignore tag) are not re-flagged."""
    guests = {
        "vm1": _make_guest("vm1", disk_total_gb=1000, disk_used_gb=10, ignore=True),
    }
    balancing = _make_balancing(threshold=500)

    result = DiskIgnoreFilter.apply(guests, balancing)

    # Already-ignored guests are not reported as newly flagged
    assert result == []
    # State remains ignored
    assert guests["vm1"].ignore is True


def test_mixed_guests_partial_flagging() -> None:
    """Only guests above the threshold should be flagged, others untouched."""
    guests = {
        "small": _make_guest("small", disk_total_gb=100, disk_used_gb=10, guest_id=101),
        "big": _make_guest("big", disk_total_gb=1000, disk_used_gb=10, guest_id=102),
        "huge": _make_guest("huge", disk_total_gb=2000, disk_used_gb=10, guest_id=103),
    }
    balancing = _make_balancing(threshold=500)

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert sorted(result) == [(102, "big"), (103, "huge")]
    assert guests["small"].ignore is False
    assert guests["big"].ignore is True
    assert guests["huge"].ignore is True


def test_unit_conversion_gb_to_bytes() -> None:
    """A threshold of 1 GB must be compared against 1024**3 bytes exactly."""
    # 1.5 GB > 1 GB threshold → flagged
    guests = {"vm1": _make_guest("vm1", disk_total_gb=1.5, disk_used_gb=0)}
    balancing = _make_balancing(threshold=1)

    result = DiskIgnoreFilter.apply(guests, balancing)

    assert result == [(100, "vm1")]
    assert guests["vm1"].ignore is True


def _make_node_metric(total_gb: float, used_gb: float) -> ProxLbData.Node.Metric:
    total = int(total_gb * GB)
    used = used_gb * GB
    free = total - used
    return ProxLbData.Node.Metric(
        total=total,
        assigned=int(used),
        used=used,
        free=free,
        assigned_percent=(used / total) * 100,
        free_percent=(free / total) * 100,
        used_percent=(used / total) * 100,
        pressure_some_percent=0.0,
        pressure_full_percent=0.0,
        pressure_some_spikes_percent=0.0,
        pressure_full_spikes_percent=0.0,
        pressure_hot=False,
    )


def _make_node(name: str, mem_total_gb: float, mem_used_gb: float) -> ProxLbData.Node:
    return ProxLbData.Node(
        name=name,
        pve_version="9",
        maintenance=False,
        pressure_hot=False,
        cpu=_make_node_metric(16, 2),
        memory=_make_node_metric(mem_total_gb, mem_used_gb),
        disk=_make_node_metric(2000, 100),
    )


def test_integration_relocate_skips_ignored_guests() -> None:
    """A guest flagged by DiskIgnoreFilter must not be relocated."""
    nodes = {
        "node1": _make_node("node1", mem_total_gb=100, mem_used_gb=90),
        "node2": _make_node("node2", mem_total_gb=100, mem_used_gb=10),
    }
    # vm1 lives on the heavily loaded node1 and has a huge disk.
    guests = {
        "vm1": _make_guest(
            "vm1",
            disk_total_gb=1000,
            disk_used_gb=10,
            node_current="node1",
        ),
    }

    balancing = _make_balancing(threshold=500)
    DiskIgnoreFilter.apply(guests, balancing)
    assert guests["vm1"].ignore is True

    proxlb_data = ProxLbData(
        guests=guests,
        ha_rules={},
        nodes=nodes,
        pools={},
        groups=ProxLbData.Groups(affinity={}),
        meta=ProxLbData.Meta(
            proxmox_api=Config.ProxmoxAPI(hosts=[], user=""),
            cluster_non_pve9=False,
            balancing=ProxLbData.Meta.Balancing(
                method=BalancingResource.Memory,
                balanciness=5,
                enable=True,
                balance=True,
                balance_types=[Config.GuestType.Vm],
                balance_larger_guests_first=False,
                balance_next_node="node2",
            ),
        ),
    )

    Calculations.relocate_guests(proxlb_data)

    # vm1 was ignored → node_target must stay equal to node_current
    assert proxlb_data.guests["vm1"].node_target == "node1"
