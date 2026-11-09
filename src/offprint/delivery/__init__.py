"""Delivery: send a finished book to the Kindle by email.

A stage of its own, outside `convert`: it uses the network and writes to the user's account
directories, which the deterministic conversion path never does.
"""

from offprint.delivery.config import DeliveryConfig, load_delivery_config
from offprint.delivery.errors import DeliveryError, VerdictBlocked
from offprint.delivery.send import Delivery, deliver, read_verdict

__all__ = [
    "Delivery",
    "DeliveryConfig",
    "DeliveryError",
    "VerdictBlocked",
    "deliver",
    "load_delivery_config",
    "read_verdict",
]
