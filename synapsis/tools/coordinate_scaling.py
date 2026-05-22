"""
Coordinate scaling for the computer-use MCP server.

Handles the mismatch between macOS logical screen coordinates (used by
cliclick), physical pixel coordinates (captured by screencapture), and the
API-constrained image dimensions sent to the model.

The Anthropic API downsamples images to fit within 1568px longest edge and
~1.15 megapixels total.  If we send a 1920px-wide screenshot, the API
silently resizes it to ~1568px, causing a ~22% coordinate error on every
click.  By pre-scaling our screenshots to fit within the API limits, the
coordinates the model returns map 1:1 to the image it actually saw.
"""

import math
from dataclasses import dataclass

# API-imposed image constraints (from Anthropic documentation)
MAX_LONG_EDGE_PX = 1568
MAX_TOTAL_PIXELS = 1_150_000


def _detect_display() -> tuple[int, int, float]:
    """Detect the actual screen dimensions and backing scale factor.

    On macOS, ``NSScreen.frame()`` can report a size that differs from
    the resolution ``screencapture`` (and ``cliclick``) actually use —
    especially on external displays or TVs with scaled resolutions.

    To get the **real** coordinate space, we take a quick screencapture
    and measure the resulting image.  ``cliclick`` operates in the same
    coordinate space, so this is the ground truth.

    The backing scale factor is still read from AppKit (defaults to 1.0).
    """
    import os
    import subprocess
    import tempfile

    # 1. Get actual capture dimensions (= cliclick coordinate space)
    capture_w, capture_h = None, None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        subprocess.run(
            ["screencapture", "-x", tmp],
            timeout=5,
            capture_output=True,
        )
        from PIL import Image  # type: ignore[import-untyped]

        with Image.open(tmp) as img:
            capture_w, capture_h = img.width, img.height
        os.unlink(tmp)
    except Exception:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)

    # 2. Get backing scale factor from AppKit (optional)
    scale = 1.0
    try:
        from AppKit import NSScreen  # type: ignore[import-untyped]

        scale = float(NSScreen.mainScreen().backingScaleFactor())
    except ImportError:
        pass

    if capture_w and capture_h:
        # screencapture gives us physical pixels; logical = physical / scale
        # But since cliclick also operates in the screencapture space,
        # we treat capture dimensions as the "logical" size with scale 1.0
        # so that api_to_screen maps directly to cliclick coordinates.
        return capture_w, capture_h, 1.0

    # Fallback: try AppKit
    try:
        from AppKit import NSScreen  # type: ignore[import-untyped]

        screen = NSScreen.mainScreen()
        frame = screen.frame()
        return (
            int(frame.size.width),
            int(frame.size.height),
            scale,
        )
    except ImportError:
        return 1920, 1080, 1.0


@dataclass
class DisplayConfig:
    """Holds display geometry and the computed target screenshot dimensions.

    The target dimensions are chosen so that the resulting screenshot image
    fits within the API constraints without any further server-side resizing.
    """

    logical_width: int
    logical_height: int
    scale_factor: float
    target_width: int
    target_height: int

    @classmethod
    def from_display(
        cls,
        logical_w: int,
        logical_h: int,
        scale_factor: float,
    ) -> "DisplayConfig":
        """Compute target screenshot dimensions from display parameters.

        The physical pixel dimensions (logical * scale_factor) are scaled
        down so that:
          1. The longest edge is at most MAX_LONG_EDGE_PX (1568).
          2. The total pixel count is at most MAX_TOTAL_PIXELS (1.15M).
        """
        phys_w = round(logical_w * scale_factor)
        phys_h = round(logical_h * scale_factor)
        long_edge = max(phys_w, phys_h)
        total_pixels = phys_w * phys_h

        s1 = MAX_LONG_EDGE_PX / long_edge if long_edge > MAX_LONG_EDGE_PX else 1.0
        s2 = (
            math.sqrt(MAX_TOTAL_PIXELS / total_pixels)
            if total_pixels > MAX_TOTAL_PIXELS
            else 1.0
        )
        scale = min(1.0, s1, s2)

        return cls(
            logical_width=logical_w,
            logical_height=logical_h,
            scale_factor=scale_factor,
            target_width=round(phys_w * scale),
            target_height=round(phys_h * scale),
        )

    def api_to_screen(self, api_x: float, api_y: float) -> tuple[float, float]:
        """Convert coordinates from API/image space to logical screen space.

        The model sees a screenshot of size (target_width x target_height).
        cliclick operates in logical screen coordinates (logical_width x
        logical_height).  This method performs the mapping between the two.
        """
        screen_x = api_x * self.logical_width / self.target_width
        screen_y = api_y * self.logical_height / self.target_height
        return screen_x, screen_y
