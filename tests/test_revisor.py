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

    def test_vista_final_corresponde_al_jpeg_exportado(self):
        """Inspeccionar a 100% equivale a inspeccionar los píxeles exportados."""
        from io import BytesIO
        import numpy as np
        from digitalizador import prepare_page
        from revisor import final_export_preview, resolution_info
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hoja.jpg"
            photo = Image.new("RGB", (320, 450), (50, 120, 170))
            photo.save(path, quality=96)
            result = final_export_preview(path, auto_crop=False)
            original, _ = prepare_page(path, auto_crop=False)
            with BytesIO() as buffer:
                original.save(buffer, "JPEG", quality=97, subsampling=0, optimize=True)
                buffer.seek(0)
                with Image.open(buffer) as jpeg_image:
                    np.testing.assert_array_equal(np.asarray(result), np.asarray(jpeg_image.convert("RGB")))
            self.assertIn("320 × 450", resolution_info(result, 1.0))
            self.assertIn("100 %", resolution_info(result, 1.0))
            result.close()
            original.close()

    def test_seleccion_por_defecto_es_preview_sin_leer_48mp(self):
        from unittest import mock
        from revisor import ReviewWorkspace
        from revisor_base import PhotoMatrix
        page = Path("hoja.jpg")
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.selected = None
        panel.paths = [page]
        panel.closed = False
        panel.corners_enabled = False
        panel.dirty = False
        panel.mode = "edit"
        panel.big_token = 0
        panel.selection_token = 0
        panel.big_image = None
        panel._set_mode_controls = mock.Mock()
        panel._highlight_selection = mock.Mock()
        panel._show_quick_preview = mock.Mock()
        panel.current_label = mock.Mock()
        panel.save_button = mock.Mock()
        panel.reset_button = mock.Mock()
        with mock.patch.object(PhotoMatrix, "choose") as heavyweight:
            panel.choose(0)
        self.assertEqual(panel.mode, "preview")
        panel._set_mode_controls.assert_called_once_with()
        panel._show_quick_preview.assert_called_once_with()
        heavyweight.assert_not_called()
        self.assertEqual(panel.selected, 0)

    def test_modo_esquinas_persiste_entre_hojas(self):
        from unittest import mock
        from revisor import ReviewWorkspace
        from revisor_base import PhotoMatrix
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.selected = 0
        panel.paths = [Path("pagina1.jpg"), Path("pagina2.jpg")]
        panel.closed = False
        panel._pending = mock.Mock(return_value=True)
        panel.dirty = False
        panel.corners_enabled = True
        panel.mode = "edit"
        panel.big_token = 0
        panel.big_image = None
        panel._set_mode_controls = mock.Mock()
        with mock.patch.object(PhotoMatrix, "choose") as original_choose:
            panel.choose(1)
        self.assertEqual(panel.mode, "edit")
        self.assertTrue(panel.corners_enabled)
        original_choose.assert_called_once_with(1)

    def test_interruptor_activar_y_desactivar(self):
        from unittest import mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.corners_enabled = False
        panel.edit_mode = mock.Mock()
        panel.preview_mode = mock.Mock()
        panel._pending = mock.Mock(return_value=True)
        panel.toggle_corners()
        self.assertTrue(panel.corners_enabled)
        panel.edit_mode.assert_called_once_with()
        panel.toggle_corners()
        self.assertFalse(panel.corners_enabled)
        panel.preview_mode.assert_called_once_with()

    def test_interruptor_no_descarta_recorte_si_cancela(self):
        from unittest import mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.corners_enabled = True
        panel._pending = mock.Mock(return_value=False)
        panel.preview_mode = mock.Mock()
        panel.toggle_corners()
        self.assertTrue(panel.corners_enabled)
        panel.preview_mode.assert_not_called()

    def test_guardar_recorte_mantiene_herramienta_activa(self):
        from unittest import mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.paths = [Path("pagina.jpg")]
        panel.selected = 0
        panel.full_size = (200, 300)
        panel.points = np.float32([[10, 10], [190, 10], [190, 290], [10, 290]])
        panel.corners_enabled = True
        panel.mode = "edit"
        panel.dirty = True
        panel.saved_indices = set()
        panel.on_save = mock.Mock()
        panel.refresh_item = mock.Mock()
        panel._highlight_selection = mock.Mock()
        panel._set_mode_controls = mock.Mock()
        panel.preview_mode = mock.Mock()
        panel.status = mock.Mock()
        panel.auto_crop = True
        self.assertTrue(panel.save())
        self.assertEqual(panel.mode, "edit")
        self.assertFalse(panel.dirty)
        panel.preview_mode.assert_not_called()
        panel.on_save.assert_called_once()
        self.assertIn(0, panel.saved_indices)

    def _fake_corner_panel(self):
        import queue
        from unittest import mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.mode = "edit"
        panel.closed = False
        panel.paths = [Path("hoja.jpg")]
        panel.selected = 0
        panel.editor_loaded_index = 0
        panel.big_token = 5
        panel.big_events = queue.Queue()
        panel.detect_steps = {}
        panel.editor_image = Image.new("RGB", (700, 900), "gray")
        panel.full_size = (700, 900)
        panel.points = np.float32([[100, 85], [585, 120],
                                    [612, 765], [80, 780]])
        panel.reset_button = mock.Mock()
        panel.status = mock.Mock()
        panel._edited = mock.Mock()
        panel._draw_editor = mock.Mock()
        panel._set_mode_controls = mock.Mock()
        panel.quick_pool = mock.Mock()
        panel.quick_pool.submit.side_effect = lambda worker: worker()
        panel.window = mock.Mock()
        return panel

    def test_deteccion_insegura_no_mueve_las_esquinas(self):
        from unittest import mock
        panel = self._fake_corner_panel()
        original = panel.points.copy()
        with mock.patch("revisor.detectar_hoja", return_value=None):
            panel.reset()
            panel.poll_large()
        np.testing.assert_array_equal(panel.points, original)
        self.assertIn("No se detectaron", panel.status.set.call_args.args[0])
        panel._edited.assert_not_called()
        panel.editor_image.close()

    def test_segunda_pulsacion_optimiza_no_repite_deteccion(self):
        from unittest import mock
        panel = self._fake_corner_panel()
        first = panel.points.copy()
        improved = first + np.float32([[8, 6], [-5, -4], [-4, 5], [8, -5]])
        with (mock.patch("revisor.detectar_hoja", return_value=first) as detector,
              mock.patch("revisor.refinar_esquinas", return_value=improved) as optimizer):
            panel.reset()
            panel.poll_large()
            self.assertEqual(panel.detect_steps[panel.paths[0]], 1)
            detector.assert_called_once()
            optimizer.assert_not_called()
            panel.reset()
            panel.poll_large()
            detector.assert_called_once()
            optimizer.assert_called_once()
            np.testing.assert_allclose(panel.points, improved)
            self.assertTrue(panel._edited.called)
        panel.editor_image.close()

    def test_primera_pulsacion_detecta_y_refina_automaticamente(self):
        from unittest import mock
        panel = self._fake_corner_panel()
        baseline = panel.points.copy()
        improved = baseline + np.float32([
            [6, 5], [-7, 6], [-6, -5], [6, -5]])
        with (mock.patch("revisor.detectar_hoja",
                         return_value=baseline) as detector,
              mock.patch("digitalizador.refine_automatic_corners",
                         return_value=improved) as pipeline):
            panel.reset()
            panel.poll_large()
        detector.assert_called_once()
        pipeline.assert_called_once()
        self.assertEqual(pipeline.call_args.kwargs["max_passes"], 2)
        np.testing.assert_allclose(panel.points, improved)
        self.assertTrue(panel._edited.called)
        panel.editor_image.close()

    def test_refinamiento_inseguro_no_reemplaza_esquinas(self):
        from unittest import mock
        panel = self._fake_corner_panel()
        panel.detect_steps[panel.paths[0]] = 1
        original = panel.points.copy()
        with mock.patch("revisor.refinar_esquinas", return_value=None):
            panel.reset()
            panel.poll_large()
        np.testing.assert_array_equal(panel.points, original)
        self.assertIn("No encontré otro borde más fiable", panel.status.set.call_args.args[0])
        panel._edited.assert_not_called()
        panel.editor_image.close()

    def test_exporta_sin_aprobacion_individual(self):
        from unittest.mock import Mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.paths = [Path("pag1.jpg"), Path("pag2.jpg")]
        panel._pending = Mock(return_value=True)
        panel.on_export = Mock()
        panel.export()
        panel.on_export.assert_called_once_with(panel)
        self.assertFalse(hasattr(panel, "approved"))
        self.assertFalse(hasattr(ReviewWorkspace, "approve"))

    def test_recorte_sin_aprobacion_individual(self):
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.selected = 0
        panel.dirty = False
        panel._edited()
        self.assertTrue(panel.dirty)

    def test_previsualiza_el_recorte_manual_con_automatico_apagado(self):
        from revisor import final_export_preview
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "foto.jpg"
            arr = np.full((640, 480, 3), (160, 10, 10), dtype=np.uint8)
            arr[80:550, 70:400] = [244, 244, 229]
            Image.fromarray(arr).save(source)
            corners = np.float32([[70, 80], [399, 80], [399, 549], [70, 549]])
            image = final_export_preview(source, auto_crop=False, corners=corners)
            self.assertLess(image.width, 350)
            self.assertLess(image.height, 490)
            image.close()

    def test_progreso_y_etapas_de_exportacion_son_visibles(self):
        from unittest.mock import Mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.export_progress = Mock()
        panel.export_message = Mock()
        panel.update_export_progress(20, 100, 80)
        self.assertIn("20/100 páginas", panel.export_message.set.call_args.args[0])
        self.assertIn("aprox.", panel.export_message.set.call_args.args[0])
        panel.export_progress.configure.assert_any_call(value=19.0)
        panel.update_export_stage("saving")
        self.assertEqual(panel.export_message.set.call_args.args[0], "Guardando PDF...")
        panel.export_progress.start.assert_called_with(12)
        panel.update_export_stage("verifying")
        self.assertEqual(panel.export_message.set.call_args.args[0],
                         "Verificando páginas del PDF...")

    def test_confirmacion_exportacion_visible_y_abrir_pdf(self):
        from unittest.mock import Mock
        from revisor import ReviewWorkspace
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "Documento final.pdf"
            target.write_bytes(b"pdf simulated")
            panel = ReviewWorkspace.__new__(ReviewWorkspace)
            panel.export_progress = Mock()
            panel.export_button = Mock()
            panel.export_message_label = Mock()
            panel.export_message = Mock()
            panel.open_pdf_button = Mock()
            panel.window = Mock()
            panel.finish_export(target, 19)
            self.assertEqual(panel.exported_file, target)
            self.assertIn("19 páginas", panel.export_message.set.call_args.args[0])
            panel.open_pdf_button.pack.assert_called_once()
            with __import__("unittest").mock.patch("os.startfile", create=True) as run:
                panel.open_exported_pdf()
                run.assert_called_once_with(str(target))

    def test_rotar_recalcula_miniatura_y_mantiene_vista_final(self):
        from unittest.mock import Mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.selected = 0
        panel.paths = [Path("foto.jpg")]
        panel._pending = Mock(return_value=True)
        panel.on_rotate = Mock(return_value=90)
        panel.refresh_item = Mock()
        panel.preview_mode = Mock()
        panel.status = Mock()
        panel.corners_enabled = True
        panel.window = Mock()
        panel.rotate(90)
        panel.on_rotate.assert_called_once_with(0, 90)
        panel.refresh_item.assert_called_once_with(0)
        panel.preview_mode.assert_called_once()
        self.assertFalse(panel.corners_enabled)

    def test_cache_compartida_evitar_decodificar_varias_veces(self):
        from collections import OrderedDict
        from threading import Lock
        from unittest.mock import Mock
        from revisor_base import PhotoMatrix
        cache = PhotoMatrix.__new__(PhotoMatrix)
        cache.closed = False
        cache.quick_lock = Lock()
        cache.quick_cache = OrderedDict()
        cache.preview_provider = Mock(side_effect=lambda _photo: (
            Image.new("RGB", (400, 600), "beige"), None))
        key = Path("foto.jpg")
        first, _ = cache.get_quick_preview(key)
        second, _ = cache.get_quick_preview(key)
        self.assertEqual(cache.preview_provider.call_count, 1)
        self.assertEqual(first.size, (400, 600))
        self.assertIsNot(first, second)
        cache.discard_quick_preview(key)
        self.assertNotIn(key, cache.quick_cache)
        first.close()
        second.close()

    def test_zoom_carga_calidad_final_solo_si_se_pide(self):
        from unittest.mock import Mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.closed = False
        panel.selected = 0
        panel.mode = "preview"
        panel.big_token = 5
        panel.full_preview = False
        panel.full_pending_token = None
        panel.paths = [Path("foto.jpg")]
        panel.manual_corners = {}
        panel.rotations = {}
        panel.auto_crop = False
        panel.quick_pool = Mock()
        panel.quality_label = Mock()
        panel._request_full_preview()
        self.assertEqual(panel.full_pending_token, 5)
        panel.quick_pool.submit.assert_called_once()
        panel._request_full_preview()
        panel.quick_pool.submit.assert_called_once()

    def test_preparacion_se_oculta_al_terminar_lote(self):
        from unittest.mock import Mock
        from revisor import ReviewWorkspace
        panel = ReviewWorkspace.__new__(ReviewWorkspace)
        panel.detection_info = Mock()
        panel.set_detection_progress(7, 100)
        self.assertEqual(panel.detection_info.set.call_args.args[0], "Preparando esquinas: 7/100")
        panel.set_detection_progress(100, 100)
        self.assertEqual(panel.detection_info.set.call_args.args[0], "")

    def test_miniaturas_respetan_monitores_pequenos(self):
        from revisor_base import matrix_thumbnail_size
        small = matrix_thumbnail_size(800, 600)
        normal = matrix_thumbnail_size(1366, 768)
        large = matrix_thumbnail_size(1920, 1080)
        for width, height in (small, normal, large):
            self.assertGreaterEqual(width, 48)
            self.assertGreaterEqual(height, 48)
        self.assertLessEqual(normal[1], 105)
        self.assertLessEqual(small[0], 65)
        self.assertGreater(large[1], normal[1])

    def test_no_permite_esquinas_cruzadas(self):
        with self.assertRaises(ValueError):
            validated_photo_corners(
                np.float32([[20, 20], [180, 180], [180, 20], [20, 180]]),
                (200, 200))


if __name__ == "__main__":
    unittest.main()
