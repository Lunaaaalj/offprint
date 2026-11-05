"""Headless Chromium for the stages that lay out HTML and screenshot it (cover, preview)."""

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

INSTALL_HINT = "run `uv run playwright install chromium`"


class BrowserUnavailableError(RuntimeError):
    """Chromium can't be started, usually because it hasn't been installed."""


@contextmanager
def chromium_page(width: int, height: int, *, scale: float = 1) -> Iterator[Page]:
    """Yield a blank page with a `width`x`height` viewport, offline so a render can't fetch.

    `scale` is how many device pixels a CSS pixel takes.
    """
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except PlaywrightError as error:
            raise BrowserUnavailableError(f"{INSTALL_HINT}: {error}") from error
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
                offline=True,
            )
            yield context.new_page()
        finally:
            browser.close()
