"""The screen a preview imitates, read from `device.yaml`."""

from dataclasses import dataclass
from functools import cache
from importlib import resources

import yaml


@dataclass(frozen=True, slots=True, kw_only=True)
class ContactSheetLayout:
    columns: int
    thumbnail_width: int
    label_height: int
    padding: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Device:
    width: int
    height: int
    scale: int
    margin: int
    top_bar: int
    bottom_bar: int
    font_size: float
    image_room: int
    clock: str
    contact_sheet: ContactSheetLayout

    @property
    def text_width(self) -> int:
        return self.width - 2 * self.margin

    @property
    def text_height(self) -> int:
        return self.height - self.top_bar - self.bottom_bar


@cache
def load_device() -> Device:
    text = (resources.files(__package__) / "device.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    layout = ContactSheetLayout(**data.pop("contact_sheet"))
    return Device(**data, contact_sheet=layout)
