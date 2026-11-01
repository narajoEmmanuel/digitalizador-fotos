"""Editar el único archivo de respaldo sin pérdida en páginas que no se tocan."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from editor_pdf import PageItem, changed_pages, initial_pages, save_edited_pdf, pdf_page_preview


class EditPdfTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.root = Path(self.context.name)
        self.pdf = self.root / 'original.pdf'
        with fitz.open() as doc:
            for color in [(255, 50, 20), (20, 250, 60), (30, 90, 250)]:
                pic = Image.new('RGB', (1400, 1800), color)
                import io
                memory = io.BytesIO()
                pic.save(memory, 'JPEG', quality=93)
                page = doc.new_page(width=595.28, height=841.89)
                page.insert_image(page.rect, stream=memory.getvalue())
            doc.save(str(self.pdf))
        self.original = self.pdf.read_bytes()
        self.photo = self.root / 'correccion.jpg'
        photo = Image.new('RGB', (1600, 2100), (10, 90, 240))
        ImageDraw.Draw(photo).rectangle((120, 110, 1480, 1970), fill=(240, 235, 215))
        photo.save(self.photo, quality=97)

    def tearDown(self):
        self.context.cleanup()

    def _image(self, doc, page):
        xref = doc[page].get_images(full=True)[0][0]
        return hashlib.sha256(doc.extract_image(xref)['image']).hexdigest()

    def test_insertar_en_medio_conserva_paginas_originales_exactas(self):
        pages = initial_pages(self.pdf)
        pages.insert(1, PageItem(image_path=self.photo))
        self.assertTrue(changed_pages(pages, 3))
        output = self.root / 'con_cuarta_pagina.pdf'
        result = save_edited_pdf(self.pdf, pages, output)
        self.assertEqual(result['pages'], 4)
        with fitz.open(self.pdf) as before, fitz.open(output) as after:
            self.assertEqual(after.page_count, 4)
            for first, second in ((0, 0), (1, 2), (2, 3)):
                self.assertEqual(self._image(before, first), self._image(after, second))
            self.assertGreater(after[1].get_images()[0][2], 1000)
        self.assertEqual(self.pdf.read_bytes(), self.original)

    def test_reemplazar_en_posicion_especifica_sin_modificar_las_otras(self):
        pages = initial_pages(self.pdf)
        pages[1] = PageItem(image_path=self.photo)
        output = self.root / 'revisado.pdf'
        save_edited_pdf(self.pdf, pages, output)
        with fitz.open(self.pdf) as before, fitz.open(output) as after:
            self.assertEqual(after.page_count, 3)
            self.assertEqual(self._image(before, 0), self._image(after, 0))
            self.assertEqual(self._image(before, 2), self._image(after, 2))
            self.assertNotEqual(self._image(before, 1), self._image(after, 1))
        self.assertEqual(self.pdf.read_bytes(), self.original)

    def test_prohibido_sobrescribir_el_original_o_un_pdf_existente(self):
        pages = initial_pages(self.pdf)
        pages[0] = PageItem(image_path=self.photo)
        with self.assertRaisesRegex(ValueError, 'original'):
            save_edited_pdf(self.pdf, pages, self.pdf)
        existing = self.root / 'existente.pdf'
        existing.write_bytes(b'IMPORTANTE')
        with self.assertRaises(FileExistsError):
            save_edited_pdf(self.pdf, pages, existing)
        self.assertEqual(existing.read_bytes(), b'IMPORTANTE')
        self.assertEqual(self.pdf.read_bytes(), self.original)

    def test_vista_pdf_y_documento_sin_exif_para_edicion(self):
        preview = pdf_page_preview(self.pdf, 1)
        self.assertGreater(preview.width, 100)
        self.assertLessEqual(preview.width, 1050)
        self.assertLessEqual(preview.height, 1150)
        self.assertEqual(len(initial_pages(self.pdf)), 3)


if __name__ == '__main__':
    unittest.main()
