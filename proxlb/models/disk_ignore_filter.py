"""
The DiskIgnoreFilter excludes guests whose disk footprint exceeds a configured
threshold from being considered for migration. Guests over the threshold are
flagged with ``ignore=True`` so that the rest of the balancing pipeline skips
them, avoiding the cost of relocating very large disks across the cluster.
"""

__author__ = "Florian Paul Azim Hoberg <gyptazy>"
__copyright__ = "Copyright (C) 2026 Florian Paul Azim Hoberg (@gyptazy)"
__license__ = "GPL-3.0"


from proxlb.utils.config_parser import Config
from proxlb.utils.logger import SystemdLogger
from proxlb.utils.proxlb_data import ProxLbData


logger = SystemdLogger()

_BYTES_PER_GB = 1024 ** 3


class DiskIgnoreFilter:
    """
    Marks guests above a disk-size threshold as ignored for balancing.

    The threshold is interpreted in gigabytes (``GB = 1024**3 bytes``) and
    compared against either the assigned (``maxdisk``) or used (``disk``)
    value of each guest, depending on ``balancing.disk_ignore_mode``.
    Guests that are already ignored (e.g. via the ``plb_ignore`` tag) are
    left untouched.
    """

    @staticmethod
    def apply(
        guests: dict[str, ProxLbData.Guest],
        balancing_config: Config.Balancing,
    ) -> list[tuple[int, str]]:
        """
        Apply the disk-ignore filter to every guest in the given mapping.

        Args:
            guests: Mapping of guest name to ``ProxLbData.Guest``. Entries
                exceeding the threshold are mutated in place by setting
                ``ignore = True``.
            balancing_config: The ``balancing`` section of the ProxLB
                configuration. The filter is a no-op unless
                ``disk_ignore_enable`` is True and ``disk_ignore_threshold``
                is set.

        Returns:
            A list of ``(guest_id, guest_name)`` tuples for every guest that
            was newly flagged as ignored during this invocation.
        """
        logger.debug("Starting: DiskIgnoreFilter.apply.")

        if not balancing_config.disk_ignore_enable:
            logger.debug("DiskIgnoreFilter disabled, skipping.")
            return []

        threshold_gb = balancing_config.disk_ignore_threshold
        if threshold_gb is None:
            logger.debug("DiskIgnoreFilter has no threshold configured, skipping.")
            return []

        threshold_bytes = threshold_gb * _BYTES_PER_GB
        mode = balancing_config.disk_ignore_mode
        ignored: list[tuple[int, str]] = []

        for guest_name, guest in guests.items():
            if guest.ignore:
                continue
            value = guest.disk.used if mode == "used" else guest.disk.total
            if value > threshold_bytes:
                guest.ignore = True
                ignored.append((guest.id, guest_name))
                logger.debug(
                    f"DiskIgnoreFilter: guest {guest_name} (id={guest.id}) "
                    f"flagged as ignored (disk.{mode}={value} bytes > "
                    f"{threshold_bytes} bytes)."
                )

        logger.debug("Finished: DiskIgnoreFilter.apply.")
        return ignored
