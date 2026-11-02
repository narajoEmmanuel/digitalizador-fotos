"""La exportación desde el revisor mantiene la posición elegida, incluso sin EXIF."""
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from digitalizador import create_pdf
from revisor_base import validated_photo_corners
import numpy as np


class ReviewFlowTests(unittest.TestCase):
    def test_orden_manual_y_foto_reemplazada_sin_exif(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            photos = [d / "despues.jpg", d / "nueva_sin_exif.jpg", d / "antes.jpg"]
            exif_late, exif_early = Image.Exif(), Image.Exif()
            exif_late[36867] = "2026:11:01 12:30:00"
            exif_early[36867] = "2026:11:01 08:30:00"
            Image.new("RGB", (380, 540), (220, 35, 35)).save(photos[0], exif=exif_late)
            Image.new("RGB", (380, 540), (35, 220, 35)).save(photos[1])
            Image.new("RGB", (380, 540), (35, 35, 220)).save(photos[2], exif=exif_early)
            original = [p.read_bytes() for p in photos]
            target = d / "archivo_aprobado.pdf"
            report = create_pdf(photos, target, auto_crop=False, preserve_input_order=True)
            self.assertEqual(report["pages"], 3)
            with fitz.open(target) as doc:
                self.assertEqual(doc.page_count, 3)
                colors = []
                for page in doc:
                    pix = page.get_pixmap(colorspace=fitz.csRGB, alpha=False)
                    pixel = (pix.height // 2 * pix.width + pix.width // 2) * 3
                    colors.append(tuple(pix.samples[pixel:pixel+3]))
            self.assertGreater(colors[0][0], colors[0][1])
            self.assertGreater(colors[1][1], colors[1][0])
            self.assertGreater(colors[2][2], colors[2][0])
            self.assertEqual(original, [p.read_bytes() for p in photos])

    def test_no_permite_esquinas_cruzadas(self):
        with self.assertRaises(ValueError):
            validated_photo_corners(
                np.float32([[20, 20], [180, 180], [180, 20], [20, 180]]),
                (200, 200))


if __name__ == "__main__":
    unittest.main()
