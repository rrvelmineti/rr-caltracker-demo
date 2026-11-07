"""Privacy claims in docs/privacy-and-consent.md that the app itself must keep. Offline."""
import io
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app  # noqa: E402

GPS_IFD = 0x8825
MAKE = 0x010F


def photo_with_location():
    exif = Image.Exif()
    exif[MAKE] = "PhoneMaker"
    exif[GPS_IFD] = {1: "N", 2: (40.0, 44.0, 54.0), 3: "W", 4: (73.0, 59.0, 10.0)}   # a real-looking location
    out = io.BytesIO()
    Image.new("RGB", (2400, 1800), "orange").save(out, format="JPEG", exif=exif)
    return out.getvalue()


class PhotoPrivacyTests(unittest.TestCase):
    def test_the_test_photo_really_carries_a_location(self):
        with Image.open(io.BytesIO(photo_with_location())) as img:
            self.assertIn(GPS_IFD, img.getexif())

    def test_location_and_camera_metadata_are_removed_before_any_ai_call(self):
        prepared = app.prepare_image(photo_with_location())
        with Image.open(io.BytesIO(prepared)) as img:
            self.assertEqual(dict(img.getexif()), {})
            self.assertNotIn("exif", img.info)
            self.assertLessEqual(max(img.size), 1600)               # resized as well
        self.assertNotIn(b"PhoneMaker", prepared)


if __name__ == "__main__":
    unittest.main()
