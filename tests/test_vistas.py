"""Verifica que la vista final lee el PDF sin alterar el archivo archivado."""
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vistas import render_pdf_page


class PreviewTests(unittest.TestCase):
    def test_pdf_real_se_lee_sin_modificarlo_y_con_zoom(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'archivo.pdf'
            with fitz.open() as doc:
                for n in range(3):
                    page = doc.new_page(width=340, height=480)
                    page.insert_text((20, 40), f'Página original {n+1}')
                doc.save(pdf)
            original = pdf.read_bytes()
            small = render_pdf_page(pdf, 1, 1)
            large = render_pdf_page(pdf, 1, 2.5)
            self.assertEqual(small.size, (340, 480))
            self.assertEqual(large.size, (850, 1200))
            self.assertEqual(original, pdf.read_bytes())

    def test_limite_memoria_y_paginas_inexistentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'archivo.pdf'
            with fitz.open() as doc:
                doc.new_page(width=1000, height=1400)
                doc.save(pdf)
            image = render_pdf_page(pdf, 0, 5, max_side=1800)
            self.assertLessEqual(max(image.size), 1800)
            with self.assertRaises(IndexError):
                render_pdf_page(pdf, 5, 1)


if __name__ == '__main__':
    unittest.main()
