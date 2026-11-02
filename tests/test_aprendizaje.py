"""Pruebas del aprendizaje local explícito. No usan fotos personales."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from aprendizaje import (apply_learning, fingerprint_photo, learning_path,
                         make_example, read_examples, save_examples)
import aprendizaje
import digitalizador


def scene(background=(35, 88, 132), paper=(232, 224, 205)):
    image = np.full((800, 600, 3), background, dtype=np.uint8)
    image[75:730, 85:535] = paper
    return image


BASE = np.float32([[85, 75], [534, 75], [534, 729], [85, 729]])
CORRECTED = np.float32([[78, 69], [541, 69], [541, 736], [78, 736]])


class LearningTests(unittest.TestCase):
    def setUp(self):
        aprendizaje._load.cache_clear()
        digitalizador._cached_auto_corners.cache_clear()

    def tearDown(self):
        aprendizaje._load.cache_clear()
        digitalizador._cached_auto_corners.cache_clear()

    def test_no_aprende_sin_pulsar_boton(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "modelo.json"
            example = make_example(scene(), BASE, CORRECTED, (600, 800), "uno")
            self.assertIsNotNone(example)
            self.assertFalse(path.exists())
            self.assertIsNone(apply_learning(scene(), BASE, path))
            # Solo guardar los puntos en la aplicación no crea el modelo.
            self.assertFalse(path.exists())

    def test_guardar_recuperar_y_aplicar_a_una_foto_similar(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "modelo.json"
            example = make_example(scene(), BASE, CORRECTED, (600, 800), "uno")
            added, count = save_examples([example], path)
            self.assertEqual((added, count), (1, 1))
            self.assertTrue(path.exists())
            self.assertEqual(len(read_examples(path)), 1)
            aprendizaje._load.cache_clear()  # Como si se reiniciara el programa.
            predicted = apply_learning(scene(), BASE, path)
            self.assertIsNotNone(predicted)
            before = np.mean(np.linalg.norm(BASE-CORRECTED, axis=1))
            after = np.mean(np.linalg.norm(predicted-CORRECTED, axis=1))
            self.assertLess(after, before)

    def test_fondo_ajeno_no_recibe_correcion_forzada(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "modelo.json"
            example = make_example(scene(), BASE, CORRECTED, (600, 800), "uno")
            save_examples([example], model)
            image = scene(background=(246, 180, 43), paper=(45, 65, 76))
            self.assertIsNone(apply_learning(image, BASE, model))

    def test_no_duplicar_fotografia_al_entrenar_otra_vez(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "modelo.json"
            example = make_example(scene(), BASE, CORRECTED, (600, 800), "uno")
            self.assertEqual(save_examples([example], model), (1, 1))
            self.assertEqual(save_examples([example], model), (0, 1))
            self.assertEqual(len(read_examples(model)), 1)

    def test_sin_movimiento_no_se_guarda_ejemplo(self):
        self.assertIsNone(make_example(scene(), BASE, BASE, (600, 800)))
        self.assertIsNone(make_example(
            scene(), BASE, BASE + np.float32([100, 0]), (600, 800)))

    def test_el_archivo_solo_contiene_vectores_no_imagenes(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "modelo.json"
            item = make_example(scene(), BASE, CORRECTED, (600, 800), "ejemplo")
            save_examples([item], model)
            text = model.read_text(encoding="utf-8")
            self.assertIn("adjustment", text)
            self.assertIn("feature", text)
            self.assertNotIn("image_bytes", text)
            self.assertNotIn("base64", text)

    def test_detector_usa_modelo_solo_despues_del_guardado(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "modelo.json"
            path = Path(folder) / "foto.jpg"
            Image.fromarray(scene()).save(path)
            sample = make_example(scene(), BASE, CORRECTED, (600, 800), "uno")
            with (mock.patch("aprendizaje.learning_path", return_value=model),
                  mock.patch("digitalizador._cached_base_corners",
                             return_value=(BASE.copy(), None))):
                before, _ = digitalizador.automatic_page_corners(path)
                np.testing.assert_array_equal(before, BASE)
                save_examples([sample], model)
                digitalizador._cached_auto_corners.cache_clear()
                after, issue = digitalizador.automatic_page_corners(path)
                self.assertIsNone(issue)
                self.assertIsNotNone(after)
                self.assertLess(
                    np.mean(np.linalg.norm(after-CORRECTED, axis=1)),
                    np.mean(np.linalg.norm(before-CORRECTED, axis=1)))
