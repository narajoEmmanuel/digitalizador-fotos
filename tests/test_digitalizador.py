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
from digitalizador import (capture_datetime, create_pdf, discover_images, prepare_page,
                          preview_pair, automatic_page_corners,
                          rotate_final_page, normalized_rotation,
                          normalize_pdf_destination, normalized_pdf_name, verify_pdf_export,
                          build_export_destination, export_success_text)
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

    def test_metadatos_exif_reutilizados(self):
        import digitalizador
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "fecha.jpg"
            self.photo_with_capture(path, "2026:11:01 15:34:55")
            digitalizador._capture_datetime_cached.cache_clear()
            with mock.patch("digitalizador.Image.open", wraps=Image.open) as reader:
                self.assertEqual(capture_datetime(path), capture_datetime(path))
            self.assertEqual(reader.call_count, 1)

    def test_deteccion_de_varias_imagenes_sin_recalcular(self):
        import digitalizador
        with tempfile.TemporaryDirectory() as d:
            photos = []
            for n in range(3):
                path = Path(d) / f"foto{n}.jpg"
                arr = np.full((680, 510, 3), (28, 82, 133), dtype=np.uint8)
                arr[85:595, 70:440] = (238, 232, 220)
                Image.fromarray(arr).save(path)
                photos.append(path)
            digitalizador._cached_auto_corners.cache_clear()
            with mock.patch("digitalizador.find_document_corners",
                            wraps=digitalizador.find_document_corners) as detector:
                for photo in photos:
                    automatic_page_corners(photo)
                calls = detector.call_count
                for photo in photos:
                    automatic_page_corners(photo)
            self.assertGreaterEqual(calls, len(photos))
            self.assertEqual(detector.call_count, calls)
            digitalizador._cached_auto_corners.cache_clear()

    def test_dos_optimizaciones_automaticas_y_cache_para_pdf(self):
        import digitalizador
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hoja.jpg"
            Image.new("RGB", (700, 950), (180, 180, 180)).save(path)
            base = np.float32([[82, 105], [608, 100], [610, 829], [80, 832]])
            first = base + np.float32([[-4, -2], [3, -2], [3, 4], [-4, 4]])
            second = first + np.float32([[-2, -1], [2, -1], [2, 2], [-2, 2]])
            digitalizador._cached_auto_corners.cache_clear()
            def detector(frame):
                factor = frame.shape[1] / 700.
                return base * factor
            with (mock.patch("digitalizador.find_document_corners", side_effect=detector) as detect,
                  mock.patch("digitalizador.refinar_esquinas",
                             side_effect=[first, second]) as refine):
                selected, problem = automatic_page_corners(path)
                self.assertIsNone(problem)
                np.testing.assert_allclose(selected, second, atol=1)
                self.assertEqual(refine.call_count, 2)
                count = detect.call_count
                # La vista y el PDF usan esquinas ya optimizadas del mismo cache.
                automatic_page_corners(path)
                preview, _ = prepare_page(path, auto_crop=True)
                preview.close()
                self.assertEqual(detect.call_count, count)
                self.assertEqual(refine.call_count, 2)
            digitalizador._cached_auto_corners.cache_clear()

    def test_refinamiento_automatico_para_si_no_mejora(self):
        import digitalizador
        candidate = np.float32([[80, 90], [520, 90], [520, 690], [80, 690]])
        frame = np.zeros((800, 600, 3), np.uint8)
        with mock.patch("digitalizador.refinar_esquinas", return_value=None) as refine:
            found = digitalizador.refine_automatic_corners(frame, candidate)
        np.testing.assert_array_equal(found, candidate)
        refine.assert_called_once_with(frame, mock.ANY)

    def test_refinamiento_automatico_descarta_geometria_insegura(self):
        import digitalizador
        candidate = np.float32([[80, 90], [520, 90], [520, 690], [80, 690]])
        unsafe = np.float32([[80, 90], [520, 90], [60, 80], [80, 690]])
        frame = np.zeros((800, 600, 3), np.uint8)
        with mock.patch("digitalizador.refinar_esquinas", return_value=unsafe) as refine:
            found = digitalizador.refine_automatic_corners(frame, candidate)
        np.testing.assert_array_equal(found, candidate)
        self.assertEqual(refine.call_count, 1)

    def test_deteccion_compartida_entre_hilos(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        import digitalizador
        with tempfile.TemporaryDirectory() as d:
            photo = Path(d) / "prueba.jpg"
            Image.new("RGB", (400, 550), "white").save(photo)
            calls = []
            def slow_detector(*_args):
                calls.append(1)
                time.sleep(.06)
                return None, "Sin esquinas"
            with mock.patch("digitalizador._cached_auto_corners", side_effect=slow_detector):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(digitalizador.automatic_page_corners, [photo]*4))
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(quad is None and reason == "Sin esquinas"
                                for quad, reason in results))

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

    def test_segunda_busqueda_refina_esquinas_desviadas(self):
        import cv2
        from recorte import refinar_esquinas
        h, w = 900, 700
        image = np.full((h, w, 3), (58, 91, 132), dtype=np.uint8)
        sheet = np.full((600, 450, 3), (245, 240, 232), dtype=np.uint8)
        for row in range(70, 590, 26):
            cv2.line(sheet, (2, row), (445, row), (180, 180, 180), 1)
        expected = np.float32([[100, 85], [585, 120], [612, 765], [80, 780]])
        corners = np.float32([[0, 0], [449, 0], [449, 599], [0, 599]])
        transform = cv2.getPerspectiveTransform(corners, expected)
        warped = cv2.warpPerspective(sheet, transform, (w, h))
        mask = cv2.warpPerspective(np.full((600, 450), 255, np.uint8),
                                   transform, (w, h))
        image[mask > 90] = warped[mask > 90]
        initial = expected + np.float32([[7, 12], [-9, 7], [-7, -11], [8, -6]])
        updated = refinar_esquinas(image, initial)
        self.assertIsNotNone(updated)
        self.assertLess(np.mean(np.linalg.norm(updated-expected, axis=1)),
                        np.mean(np.linalg.norm(initial-expected, axis=1)) * .6)
        # Si las esquinas ya coinciden con la hoja, no forzar desplazamientos.
        self.assertIsNone(refinar_esquinas(image, expected))

    def test_refinamiento_amplio_y_lados_inclinados(self):
        import cv2
        from recorte import refinar_esquinas
        h, w = 900, 700
        photo = np.full((h, w, 3), (35, 92, 135), dtype=np.uint8)
        page = np.full((600, 440, 3), (240, 234, 218), dtype=np.uint8)
        for y in range(55, 580, 35):
            cv2.line(page, (4, y), (431, y), (180, 182, 173), 1)
        truth = np.float32([[102, 105], [579, 93], [606, 777], [80, 806]])
        src = np.float32([[0, 0], [439, 0], [439, 599], [0, 599]])
        t = cv2.getPerspectiveTransform(src, truth)
        warped = cv2.warpPerspective(page, t, (w, h))
        mask = cv2.warpPerspective(
            np.full((600, 440), 255, np.uint8), t, (w, h))
        photo[mask > 90] = warped[mask > 90]
        # Ambas puntas de un mismo lado se desvían de forma distinta,
        # por encima de la búsqueda anterior de unos 24 px.
        initial = truth + np.float32([[38, 45], [-40, 28], [-35, -38], [41, -45]])
        found = refinar_esquinas(photo, initial)
        self.assertIsNotNone(found)
        old_error = np.mean(np.linalg.norm(initial-truth, axis=1))
        new_error = np.mean(np.linalg.norm(found-truth, axis=1))
        self.assertLess(new_error, old_error*.65)

    def test_refinamiento_sin_bordes_no_modifica_la_hoja(self):
        from recorte import refinar_esquinas
        image = np.full((750, 600, 3), (210, 210, 210), dtype=np.uint8)
        approximate = np.float32([[70, 70], [540, 70], [540, 680], [70, 680]])
        self.assertIsNone(refinar_esquinas(image, approximate))

    def test_marco_fotografico_no_es_una_hoja(self):
        # Con solo el límite de la imagen, se conserva la foto sin cortar.
        photo = np.full((700, 500, 3), (190, 180, 170), dtype=np.uint8)
        import cv2
        cv2.rectangle(photo, (1, 1), (498, 698), (10, 20, 30), 3)
        self.assertIsNone(detectar_hoja(photo))

    def test_vista_previa_y_pdf_comparten_esquinas(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hoja.jpg"
            image = np.full((800, 600, 3), (40, 80, 120), dtype=np.uint8)
            image[90:710, 80:520] = [240, 238, 225]
            Image.fromarray(image).save(path, quality=96)
            quad, reason = automatic_page_corners(path)
            self.assertIsNone(reason)
            self.assertIsNotNone(quad)
            original, thumbnail, preview_cropped = preview_pair(path, True, None)
            full, final_cropped = prepare_page(path, True)
            self.assertTrue(preview_cropped)
            self.assertTrue(final_cropped)
            self.assertAlmostEqual(thumbnail.width/thumbnail.height,
                                   full.width/full.height, delta=.015)
            original.close()
            thumbnail.close()
            full.close()

    def test_recorte_inseguro_no_se_deforma_y_se_marca(self):
        import digitalizador
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hoja.jpg"
            Image.new("RGB", (700, 1000), "beige").save(path)
            quad = np.float32([[70, 80], [630, 80], [630, 920], [70, 920]])
            digitalizador._cached_auto_corners.cache_clear()
            with mock.patch("digitalizador.find_document_corners",
                            side_effect=[quad, None]):
                corners, reason = automatic_page_corners(path)
            self.assertIsNone(corners)
            self.assertIn("inestables", reason)
            digitalizador._cached_auto_corners.cache_clear()

    def test_recorte_manual_tiene_prioridad_sobre_detector(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hoja.jpg"
            image = np.full((850, 640, 3), (25, 80, 130), dtype=np.uint8)
            image[80:760, 70:570] = 235
            Image.fromarray(image).save(path)
            corners = np.float32([[70, 80], [569, 80], [569, 759], [70, 759]])
            with mock.patch("digitalizador.automatic_page_corners",
                            side_effect=AssertionError("Detector no debe ejecutarse")):
                original, thumbnail, cropped_preview = preview_pair(path, False, corners)
                final, cropped_pdf = prepare_page(path, False, corners)
            self.assertTrue(cropped_preview)
            self.assertTrue(cropped_pdf)
            self.assertAlmostEqual(thumbnail.width/thumbnail.height,
                                   final.width/final.height, delta=.02)
            original.close()
            thumbnail.close()
            final.close()

    def test_giro_horario_y_antihorario_sin_perder_pixeles(self):
        expected = np.zeros((2, 3, 3), dtype=np.uint8)
        for y in range(2):
            for x in range(3):
                expected[y, x] = (y*100 + x*20, 15, 15)
        image = Image.fromarray(expected, "RGB")
        right = rotate_final_page(image, 90)
        self.assertEqual(right.size, (2, 3))
        np.testing.assert_array_equal(np.asarray(right), np.rot90(expected, -1))
        left = rotate_final_page(right, -90)
        np.testing.assert_array_equal(np.asarray(left), expected)
        left.close()
        self.assertEqual(normalized_rotation(450), 90)
        with self.assertRaisesRegex(ValueError, "giro"):
            normalized_rotation(45)

    def test_giro_se_exporta_y_conserva_la_foto_original(self):
        import fitz
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "girada.jpg"
            image = np.zeros((120, 240, 3), np.uint8)
            image[:, :120] = [225, 55, 55]
            image[:, 120:] = [50, 140, 220]
            Image.fromarray(image).save(source, quality=98)
            original = source.read_bytes()
            orig, small, cropped = preview_pair(source, False, None, rotation=90)
            self.assertEqual(small.size, (120, 240))
            preview, _ = prepare_page(source, False, rotation=90)
            self.assertEqual(preview.size, small.size)
            target = Path(folder) / "orientada.pdf"
            create_pdf([source], target, auto_crop=False,
                       preserve_input_order=True, rotations={source: 90})
            with fitz.open(target) as pdf:
                self.assertEqual(pdf.page_count, 1)
                self.assertGreater(pdf[0].rect.height, pdf[0].rect.width)
                page_img = pdf[0].get_images(full=True)[0]
                embedded = fitz.Pixmap(pdf, page_img[0])
                self.assertEqual((embedded.width, embedded.height), (120, 240))
            self.assertEqual(source.read_bytes(), original)
            orig.close()
            small.close()
            preview.close()

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

    def test_nombre_de_pdf_elegido_se_conserva(self):
        import fitz
        self.assertEqual(normalized_pdf_name("  Archivo de Alemán  "), "Archivo de Alemán.pdf")
        self.assertEqual(normalized_pdf_name("Archivo de Alemán.PDF"), "Archivo de Alemán.pdf")
        with self.assertRaisesRegex(ValueError, "extensión"):
            normalize_pdf_destination(r"C:\\Documentos\\archivo.txt")
        with tempfile.TemporaryDirectory() as d:
            selected = normalize_pdf_destination(str(Path(d) / "Mis apuntes especiales.PDF"))
            self.assertEqual(selected.name, "Mis apuntes especiales.pdf")
            source = Path(d) / "pagina.jpg"
            self.photo_with_capture(source, "2026:11:01 11:00:00")
            result = create_pdf([source], selected, auto_crop=False, preserve_input_order=True)
            self.assertEqual(result["file"], str(selected))
            self.assertTrue(selected.exists())
            verify_pdf_export(selected, 1)
            with fitz.open(selected) as pdf:
                self.assertEqual(pdf.metadata["title"], selected.stem)

    def test_nombre_escrito_es_el_nombre_final_y_solo_se_elije_carpeta(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            wanted = "Documentos de Alemán y Francés 2026"
            destination = build_export_destination(folder, wanted)
            self.assertEqual(destination.parent, folder)
            self.assertEqual(destination.name, wanted + ".pdf")
            self.assertEqual(destination.suffix, ".pdf")
            self.assertEqual(export_success_text(destination, 8),
                             f"✓ PDF guardado: {wanted}.pdf\\n8 páginas · {folder}".replace("\\n", "\n"))
            with self.assertRaisesRegex(ValueError, "carpeta"):
                build_export_destination(folder / "no_existe", wanted)

    def test_pdf_no_permite_sobrescribir_el_original(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "pagina.jpg"
            self.photo_with_capture(source, "2026:11:01 11:00:00")
            pdf = Path(d) / "mis apuntes.pdf"
            create_pdf([source], pdf, auto_crop=False, preserve_input_order=True)
            before = pdf.read_bytes()
            with self.assertRaises(FileExistsError):
                create_pdf([source], pdf, auto_crop=False, preserve_input_order=True)
            self.assertEqual(before, pdf.read_bytes())

    def test_recorte_manual_con_automatico_desactivado_se_exporta(self):
        import fitz
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "pagina.jpg"
            arr = np.zeros((640, 480, 3), dtype=np.uint8)
            arr[:] = [190, 10, 10]
            arr[70:560, 60:420] = [240, 240, 230]
            Image.fromarray(arr).save(source, quality=98)
            corners = np.float32([[60, 70], [419, 70], [419, 559], [60, 559]])
            preview, cropped = prepare_page(source, auto_crop=False, manual_corners=corners)
            self.assertTrue(cropped)
            self.assertLess(preview.width, 400)
            self.assertLess(preview.height, 530)
            preview.close()
            out = Path(d) / "Hoja recortada.pdf"
            create_pdf([source], out, auto_crop=False,
                       manual_corners={source: corners}, preserve_input_order=True)
            with fitz.open(out) as pdf:
                self.assertEqual(pdf.page_count, 1)
                pix = pdf[0].get_pixmap()
                center = (pix.height//2 * pix.width + pix.width//2)*3
                color = pix.samples[center:center+3]
                self.assertGreater(color[0], 210)
                self.assertGreater(color[1], 210)
                self.assertGreater(color[2], 200)

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
