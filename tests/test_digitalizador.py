"""Pruebas locales sin documentos privados ni OCR."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from digitalizador import capture_datetime, create_pdf, discover_images, prepare_page
from recorte import detectar_hoja


class DigitalizadorTests(unittest.TestCase):
    @staticmethod
    def photo_with_capture(path: Path, taken: str, subsec: str | None = None,
                           offset: str | None = None, color=(230, 202, 108)):
        exif = Image.Exif()
        exif[36867] = taken  # EXIF DateTimeOriginal
        if subsec is not None:
            exif[37521] = subsec
        if offset is not None:
            exif[36881] = offset
        Image.new("RGB", (400, 550), color).save(path, exif=exif)

    def test_orden_por_captura_no_por_nombre_ni_fecha_de_descarga(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = root / "z_ultimo_nombre.jpg"
            second = root / "a_primer_nombre.jpg"
            third = root / "b_segundo_nombre.jpg"
            self.photo_with_capture(first, "2026:11:01 09:01:01")
            self.photo_with_capture(second, "2026:11:01 09:01:03")
            self.photo_with_capture(third, "2026:11:01 09:01:02")
            # Simula que OneDrive cambió las fechas de descarga/modificación.
            os.utime(first, (2000000000, 2000000000))
            os.utime(second, (1000000000, 1000000000))
            os.utime(third, (1500000000, 1500000000))
            (root / "ignorar.txt").write_text("No es una foto")
            self.assertEqual([p.name for p in discover_images(root)],
                             [first.name, third.name, second.name])

    def test_metadatos_subsegundos_y_zona_horaria(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p1, p2 = root / "a.jpg", root / "b.jpg"
            self.photo_with_capture(p1, "2026:11:01 12:00:00", "901", "+02:00")
            self.photo_with_capture(p2, "2026:11:01 04:00:00", "120", "-06:00")
            self.assertEqual(capture_datetime(p1).microsecond, 901000)
            # Ambos son las 10:00 UTC; los subsegundos determinan el orden.
            self.assertEqual(discover_images(root), [p2, p1])

    def test_sin_exif_no_utiliza_nombres_ni_fechas_del_sistema(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "IMG_0001.jpg"
            Image.new("RGB", (100, 100), "white").save(p)
            os.utime(p, (2000000000, 2000000000))
            with self.assertRaisesRegex(ValueError, "DateTimeOriginal"):
                discover_images(root)
            output = root / "sin-orden.pdf"
            with self.assertRaisesRegex(ValueError, "DateTimeOriginal"):
                create_pdf([p], output, auto_crop=False)
            self.assertFalse(output.exists())

    def test_deteccion_hoja_con_fondo_contrastado(self):
        photo = np.full((800, 600, 3), (56, 70, 90), dtype=np.uint8)
        photo[100:700, 85:515] = (237, 232, 212)
        quad = detectar_hoja(photo)
        self.assertIsNotNone(quad)
        self.assertTrue(np.all(np.isfinite(quad)))
        self.assertGreater(np.ptp(quad[:, 0]), 350)
        self.assertGreater(np.ptp(quad[:, 1]), 500)

    def test_fondo_estampado_papel_perforado_no_selecciona_el_marco(self):
        # Simula un fondo de color con patrones, renglones y perforaciones.
        import cv2
        h, w = 850, 630
        yy, xx = np.indices((h, w))
        photo = np.empty((h, w, 3), dtype=np.uint8)
        photo[:, :, 0] = 68 + (18 * np.sin(xx / 25)).astype(np.int16)
        photo[:, :, 1] = 92 + (16 * np.cos(yy / 29)).astype(np.int16)
        photo[:, :, 2] = 103 + (18 * np.sin((xx + yy) / 17)).astype(np.int16)
        page = np.full((600, 405, 3), (238, 237, 230), dtype=np.uint8)
        for row in range(80, 590, 30):
            cv2.line(page, (0, row), (405, row), (166, 189, 173), 1)
        for row in range(22, 590, 48):
            cv2.circle(page, (392, row), 9, (84, 85, 88), -1)
        expected = np.float32([[101, 112], [493, 94], [528, 735], [84, 746]])
        original_corners = np.float32([[0, 0], [404, 0], [404, 599], [0, 599]])
        transform = cv2.getPerspectiveTransform(original_corners, expected)
        overlay = cv2.warpPerspective(page, transform, (w, h))
        mask = cv2.warpPerspective(np.full(page.shape[:2], 255, np.uint8),
                                   transform, (w, h))
        photo[mask > 80] = overlay[mask > 80]
        detected = detectar_hoja(photo)
        self.assertIsNotNone(detected)
        np.testing.assert_allclose(detected, expected, atol=18)
        self.assertGreater(np.min(detected[:, 0]), 60)
        self.assertLess(np.max(detected[:, 0]), w - 60)

    def test_marco_fotografico_no_es_una_hoja(self):
        # Con solo el límite de la imagen, se conserva la foto sin cortar.
        photo = np.full((700, 500, 3), (190, 180, 170), dtype=np.uint8)
        import cv2
        cv2.rectangle(photo, (1, 1), (498, 698), (10, 20, 30), 3)
        self.assertIsNone(detectar_hoja(photo))

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
                photo = root / f'foto{n}.jpg'
                self.photo_with_capture(photo, f"2026:11:01 10:00:{n:02d}",
                                        color=(220, 150+n, 105))
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

    def test_crear_pdf_reordena_aunque_reciba_rutas_invertidas(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            before, after = root / "ZZZ.jpg", root / "AAA.jpg"
            self.photo_with_capture(before, "2026:11:01 11:00:00")
            self.photo_with_capture(after, "2026:11:01 11:00:02")
            from digitalizador import prepare_page
            with mock.patch("digitalizador.prepare_page", wraps=prepare_page) as called:
                result = create_pdf([after, before], root / "ordenado.pdf", auto_crop=False)
            self.assertEqual([call.args[0] for call in called.call_args_list], [before, after])
            self.assertEqual(result["pages"], 2)


if __name__ == '__main__':
    unittest.main()
