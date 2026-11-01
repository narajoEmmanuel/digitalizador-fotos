"""Pruebas locales sin documentos privados ni OCR."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from digitalizador import create_pdf, discover_images, prepare_page
from recorte import detectar_hoja


class DigitalizadorTests(unittest.TestCase):
    def test_orden_natural(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("foto10.png", "foto2.jpg", "foto1.jpeg", "notas.txt"):
                (root / name).touch()
            self.assertEqual([p.name for p in discover_images(root)],
                             ["foto1.jpeg", "foto2.jpg", "foto10.png"])

    def test_deteccion_hoja_con_fondo_contrastado(self):
        photo = np.full((800, 600, 3), (56, 70, 90), dtype=np.uint8)
        photo[100:700, 85:515] = (237, 232, 212)
        quad = detectar_hoja(photo)
        self.assertIsNotNone(quad)
        self.assertTrue(np.all(np.isfinite(quad)))
        self.assertGreater(np.ptp(quad[:, 0]), 350)
        self.assertGreater(np.ptp(quad[:, 1]), 500)

    def test_pagina_se_recorta_y_preserva_color(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'foto1.png'
            arr = np.full((800, 600, 3), (35, 45, 60), dtype=np.uint8)
            arr[100:700, 90:510] = (234, 203, 109)
            Image.fromarray(arr).save(path)
            before = path.read_bytes()
            result, cropped = prepare_page(path)
            self.assertTrue(cropped)
            self.assertLess(result.width, 520)
            self.assertGreater(result.height, 550)
            center = np.asarray(result)[result.height//2, result.width//2]
            self.assertGreater(int(center[0]), int(center[2]) + 70)
            result.close()
            self.assertEqual(path.read_bytes(), before)

    def test_pdf_personalizado_sin_cambiar_original(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            photos = []
            for n in range(1, 4):
                photo = root / f'foto{n}.png'
                Image.new('RGB', (400, 550), (220, 150+n, 105)).save(photo)
                photos.append(photo)
            originals = [p.read_bytes() for p in photos]
            target = root / 'Mi documento digitalizado.pdf'
            result = create_pdf(photos, target, auto_crop=False)
            self.assertTrue(target.is_file())
            self.assertGreater(target.stat().st_size, 1000)
            self.assertEqual(result['pages'], 3)
            self.assertEqual(result['errors'], [])
            self.assertEqual([p.read_bytes() for p in photos], originals)
            self.assertIn(b'/Type /Page', target.read_bytes())


if __name__ == '__main__':
    unittest.main()
