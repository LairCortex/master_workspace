from enum import Enum


class SheetOrientation(Enum):
    """Page orientation, shared by all pages of one template."""
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


#: A4 format, pt (210 × 297 mm)
A4_PORTRAIT_SIZE = (595.28, 841.89)
A4_LANDSCAPE_SIZE = (841.89, 595.28)


def a4_size(orientation: SheetOrientation) -> tuple[float, float]:
    """Return (width, height) of an A4 page in the given orientation."""
    return A4_PORTRAIT_SIZE if orientation is SheetOrientation.PORTRAIT else A4_LANDSCAPE_SIZE
