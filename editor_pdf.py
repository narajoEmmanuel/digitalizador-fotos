"""Editor conservador de PDF: inserta o sustituye páginas sin recomprimir las existentes."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import queue
import tempfile
import threading
from typing import Callable

import fitz
from PIL import Image


@dataclass(frozen=True)
class PageItem:
    """Una página del PDF original o una fotografía que se va a insertar."""
    source_index: int | None = None  # Base cero, página original.
    image_path: Path | None = None


def initial_pages(pdf_path: Path) -> list[PageItem]:
    with fitz.open(pdf_path) as doc:
        if doc.needs_pass:
            raise ValueError("Este PDF tiene contraseña. Usa primero una copia sin cifrar.")
        if doc.page_count == 0:
            raise ValueError("El PDF no tiene páginas.")
        return [PageItem(source_index=i) for i in range(doc.page_count)]


def changed_pages(pages: list[PageItem], original_count: int) -> bool:
    return pages != [PageItem(source_index=i) for i in range(original_count)]


def pdf_page_preview(pdf_path: Path, index: int, max_width: int = 1050,
                     max_height: int = 1150) -> Image.Image:
    """Renderizar únicamente la página solicitada, sin rasterizar el resto."""
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(index)
        zoom = min(max_width / page.rect.width, max_height / page.rect.height, 2.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, colorspace=fitz.csRGB)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def image_page_preview(path: Path, max_width: int = 1050,
                       max_height: int = 1150) -> Image.Image:
    """Usa miniatura y recorte rápido, sin procesar la foto de alta resolución."""
    from digitalizador import preview_image
    from recorte import detectar_hoja, ordenar_esquinas
    import cv2
    import numpy as np
    im, _ = preview_image(path, max(max_width, max_height))
    arr = np.asarray(im)
    corners = detectar_hoja(arr)
    if corners is not None:
        tl, tr, br, bl = ordenar_esquinas(corners)
        width = max(1, int(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl))))
        height = max(1, int(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr))))
        out = np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]])
        warped = cv2.warpPerspective(arr, cv2.getPerspectiveTransform(corners.astype('float32'), out),
                                     (width, height), flags=cv2.INTER_LINEAR)
        im = Image.fromarray(warped, 'RGB')
    im.thumbnail((max_width, max_height), Image.Resampling.BILINEAR)
    return im


def save_edited_pdf(source: Path, pages: list[PageItem], destination: Path,
                    progress: Callable[[int, int], None] | None = None) -> dict:
    """Crea copia de forma atómica. Las páginas existentes se copian como objetos PDF."""
    from digitalizador import prepare_page

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        raise ValueError("Para proteger el archivo original, guarda una copia con otro nombre.")
    if not pages:
        raise ValueError("El documento debe contener al menos una página.")
    if destination.exists():
        raise FileExistsError(f"La salida ya existe: {destination}. Usa otro nombre para no sobrescribir un PDF.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.digitalizador_', suffix='.pdf',
                                     dir=destination.parent, delete=False) as f:
        temp = Path(f.name)
    try:
        with fitz.open(source) as original, fitz.open() as target:
            if original.needs_pass:
                raise ValueError("El documento está protegido con contraseña.")
            target.set_metadata({"title": destination.stem, "creator": "Digitalizador de Fotos"})
            for n, item in enumerate(pages, 1):
                if item.source_index is not None:
                    if not (0 <= item.source_index < original.page_count):
                        raise ValueError(f"Página original inexistente: {item.source_index+1}")
                    target.insert_pdf(original, from_page=item.source_index,
                                      to_page=item.source_index, annots=True, links=True)
                elif item.image_path is not None:
                    if not item.image_path.is_file():
                        raise FileNotFoundError(f"La nueva fotografía ya no existe: {item.image_path}")
                    photo, _ = prepare_page(item.image_path, auto_crop=True)
                    try:
                        width, height = photo.size
                        if min(width, height) < 800:
                            raise ValueError(f"La fotografía {item.image_path.name} tiene resolución insuficiente ({width}x{height}).")
                        buffer = BytesIO()
                        photo.save(buffer, format='JPEG', quality=97, subsampling=0, optimize=True)
                        page_w = 595.28 if width <= height else 841.89
                        page_h = page_w * height / width
                        page = target.new_page(width=page_w, height=page_h)
                        page.insert_image(page.rect, stream=buffer.getvalue())
                    finally:
                        photo.close()
                else:
                    raise ValueError("Página sin fuente.")
                if progress:
                    progress(n, len(pages))
            # Evitar una segunda compresión de las páginas existentes.
            target.save(str(temp), garbage=0, deflate=False)
        with fitz.open(temp) as check:
            if check.page_count != len(pages):
                raise RuntimeError("Falló la validación del número de páginas del PDF.")
            for page in check:
                if page.rect.is_empty or page.rect.is_infinite:
                    raise RuntimeError("Se detectó una página inválida en el PDF generado.")
        os.replace(temp, destination)
        return {"file": str(destination), "pages": len(pages), "bytes": destination.stat().st_size}
    finally:
        if temp.exists():
            temp.unlink()


class PdfEditorWindow:
    def __init__(self, parent, pdf_path: Path):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.parent = parent
        self.path = pdf_path
        self.pages = initial_pages(pdf_path)
        self.original_count = len(self.pages)
        self.history: list[tuple[list[PageItem], int]] = []
        self.saved_pages = list(self.pages)
        self.window = tk.Toplevel(parent)
        self.window.title(f"Editar PDF: {pdf_path.name}")
        self.window.geometry('1090x770')
        self.window.minsize(850, 600)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.events = queue.Queue()
        self.render_pool = ThreadPoolExecutor(max_workers=2)
        self.overview_pool = ThreadPoolExecutor(max_workers=1)
        self.preview_cache: OrderedDict[PageItem, Image.Image] = OrderedDict()
        self.preview_pending: set[PageItem] = set()
        self.overview_cache: OrderedDict[PageItem, Image.Image] = OrderedDict()
        self.overview_window = None
        self.overview_generation = 0
        self.overview_buttons = {}
        self.overview_photos = {}
        self.last_image = None
        self.preview_generation = 0
        self.render_after = None
        self.busy = False
        self.position = tk.StringVar(value='')
        self.details = tk.StringVar(value='')
        self.state = tk.StringVar(value='Abriendo el PDF...')
        self.page_jump = tk.StringVar(value='1')

        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Revisar y corregir PDF', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='No necesitas las fotos originales. Las páginas ya existentes se conservan sin volver a comprimir.').pack(anchor='w', pady=(3, 8))
        ttk.Label(outer, textvariable=self.details).pack(anchor='w', pady=(0, 10))

        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=(0, 10))
        self.replace_btn = ttk.Button(actions, text='Reemplazar página con foto', command=self.replace_photo)
        self.replace_btn.pack(side='left', padx=(0, 8))
        self.before_btn = ttk.Button(actions, text='Insertar antes', command=lambda: self.insert_photo(False))
        self.before_btn.pack(side='left', padx=(0, 8))
        self.after_btn = ttk.Button(actions, text='Insertar después', command=lambda: self.insert_photo(True))
        self.after_btn.pack(side='left')
        self.undo_btn = ttk.Button(actions, text='Deshacer', command=self.undo)
        self.undo_btn.pack(side='left', padx=(10, 0))
        self.undo_btn.state(['disabled'])
        self.save_btn = ttk.Button(actions, text='Guardar PDF revisado...', command=self.save)
        self.save_btn.pack(side='right')

        panes = ttk.Panedwindow(outer, orient='horizontal')
        panes.pack(fill='both', expand=True)
        left = ttk.Frame(panes, width=235)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=4)
        ttk.Label(left, text='Páginas del documento', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 5))
        scroller = ttk.Frame(left)
        scroller.pack(fill='both', expand=True)
        self.listbox = tk.Listbox(scroller, font=('Segoe UI', 10), exportselection=False,
                                  activestyle='none', selectmode='browse')
        scrollbar = ttk.Scrollbar(scroller, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.listbox.bind('<<ListboxSelect>>', self.select)

        navigation = ttk.Frame(right)
        navigation.pack(fill='x', padx=(12, 0), pady=(0, 8))
        ttk.Button(navigation, text='◀ Anterior', command=lambda: self.go(-1)).pack(side='left')
        ttk.Label(navigation, textvariable=self.position, font=('Segoe UI', 11, 'bold')).pack(side='left', padx=12)
        ttk.Button(navigation, text='Siguiente ▶', command=lambda: self.go(1)).pack(side='left')
        ttk.Label(navigation, text='Ir a:').pack(side='left', padx=(18, 5))
        jump = ttk.Entry(navigation, textvariable=self.page_jump, width=6)
        jump.pack(side='left')
        jump.bind('<Return>', self.go_to_page)
        ttk.Button(navigation, text='Ir', command=self.go_to_page).pack(side='left', padx=(5, 0))
        ttk.Button(navigation, text='Ver 16 páginas', command=self.open_overview).pack(side='right')

        frame = tk.Frame(right, bg='#e3e6ea')
        frame.pack(fill='both', expand=True, padx=(12, 0))
        self.preview = tk.Label(frame, bg='#e3e6ea', text='Cargando página...', font=('Segoe UI', 11))
        self.preview.pack(fill='both', expand=True)
        ttk.Label(right, textvariable=self.state).pack(anchor='w', padx=(12, 0), pady=(7, 0))
        self.window.bind('<Alt-Left>', lambda _e: self.go(-1))
        self.window.bind('<Alt-Right>', lambda _e: self.go(1))
        self.window.bind('<Prior>', lambda _e: self.go(-1))
        self.window.bind('<Next>', lambda _e: self.go(1))
        self._sync_list(0)
        self.window.after(75, self._poll)

    def _sync_list(self, active: int):
        self.listbox.delete(0, 'end')
        for n, item in enumerate(self.pages, 1):
            if item.image_path:
                label = f'{n:>4}.  Nueva: {item.image_path.name}'
            else:
                label = f'{n:>4}.  Página original {item.source_index+1}'
            self.listbox.insert('end', label)
        self.details.set(f'{len(self.pages)} páginas en edición  |  PDF original: {self.path.stat().st_size/1024/1024:.1f} MB  |  Cambios: {"sí" if changed_pages(self.pages, self.original_count) else "no"}')
        self.listbox.selection_set(active)
        self.listbox.activate(active)
        self.listbox.see(active)
        self.select()

    def current(self):
        choices = self.listbox.curselection()
        return choices[0] if choices else 0

    def go(self, offset: int):
        self.set_active(max(0, min(len(self.pages)-1, self.current()+offset)))

    def go_to_page(self, _event=None):
        from tkinter import messagebox
        try:
            i = int(self.page_jump.get()) - 1
            if not (0 <= i < len(self.pages)):
                raise ValueError
        except ValueError:
            messagebox.showwarning('Número de página', f'Escribe un número entre 1 y {len(self.pages)}.', parent=self.window)
            return
        self.set_active(i)

    def set_active(self, index):
        self.listbox.selection_clear(0, 'end')
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)
        self.select()

    def select(self, _event=None):
        if not self.pages:
            return
        i = self.current()
        self.position.set(f'Página {i+1} de {len(self.pages)}')
        self.page_jump.set(str(i+1))
        self.preview_generation += 1
        gen = self.preview_generation
        if self.render_after:
            self.window.after_cancel(self.render_after)
        self.render_after = self.window.after(75, lambda: self._request_preview(gen, self.pages[i]))

    def _request_preview(self, gen: int, item: PageItem):
        if gen != self.preview_generation:
            return
        cached = self.preview_cache.get(item)
        if cached is not None:
            self.preview_cache.move_to_end(item)
            self._show(cached)
            self._prefetch_neighbors()
            return
        self.preview.configure(text='Preparando vista previa...', image='')
        self.state.set('Cargando miniatura; puedes seguir navegando.')
        self._submit_preview(item, gen)

    def _submit_preview(self, item: PageItem, gen: int):
        if item in self.preview_pending or item in self.preview_cache:
            return
        self.preview_pending.add(item)

        def worker():
            try:
                if item.image_path is not None:
                    preview = image_page_preview(item.image_path, 740, 560)
                else:
                    preview = pdf_page_preview(self.path, item.source_index, 740, 560)
                self.events.put(('render', gen, item, preview, None))
            except Exception as exc:
                self.events.put(('render', gen, item, None, str(exc)))

        self.render_pool.submit(worker)

    def _prefetch_neighbors(self):
        """Carga las páginas de al lado después de mostrar la actual, sin retrasarla."""
        current = self.current()
        for index in (current + 1, current - 1):
            if 0 <= index < len(self.pages):
                self._submit_preview(self.pages[index], -1)

    def open_overview(self):
        """Vista de contacto de 16 páginas para revisar el PDF sin abrir una a una."""
        from tkinter import ttk
        tk = self.tk
        if self.overview_window is not None and self.overview_window.winfo_exists():
            self.overview_window.lift()
            return
        popup = tk.Toplevel(self.window)
        popup.title('Vista general del PDF, 16 páginas a la vez')
        popup.geometry('1000x790')
        popup.minsize(730, 530)
        self.overview_window = popup
        self.overview_photos = {}
        wrapper = ttk.Frame(popup, padding=12)
        wrapper.pack(fill='both', expand=True)
        control = ttk.Frame(wrapper)
        control.pack(fill='x', pady=(0, 12))
        self.overview_label = tk.StringVar()
        ttk.Button(control, text='◀ 16 anteriores', command=lambda: self._overview_batch(self.overview_start - 16)).pack(side='left')
        ttk.Label(control, textvariable=self.overview_label, font=('Segoe UI', 11, 'bold')).pack(side='left', padx=18)
        ttk.Button(control, text='16 siguientes ▶', command=lambda: self._overview_batch(self.overview_start + 16)).pack(side='left')
        ttk.Label(control, text='Selecciona una miniatura para ir a esa página.').pack(side='right')
        self.overview_frame = ttk.Frame(wrapper)
        self.overview_frame.pack(fill='both', expand=True)
        self._overview_batch((self.current() // 16) * 16)
        popup.protocol('WM_DELETE_WINDOW', self._close_overview)

    def _close_overview(self):
        self.overview_generation += 1
        if self.overview_window is not None and self.overview_window.winfo_exists():
            self.overview_window.destroy()
        self.overview_window = None
        self.overview_photos.clear()

    def _overview_batch(self, start: int):
        if self.overview_window is None or not self.overview_window.winfo_exists():
            return
        start = max(0, min(start, ((len(self.pages) - 1) // 16) * 16))
        self.overview_start = start
        self.overview_generation += 1
        generation = self.overview_generation
        batch = list(enumerate(self.pages[start:start + 16], start))
        self.overview_label.set(f'Páginas {start + 1} a {start + len(batch)} de {len(self.pages)}')
        for child in self.overview_frame.winfo_children():
            child.destroy()
        self.overview_buttons.clear()
        self.overview_photos.clear()
        to_render = []
        for offset, (idx, item) in enumerate(batch):
            r, c = divmod(offset, 4)
            holder = self.ttk.Frame(self.overview_frame)
            holder.grid(row=r, column=c, sticky='nsew', padx=5, pady=5)
            btn = self.tk.Button(holder, bg='#e8edf1', relief='flat', cursor='hand2',
                                 text=f'Cargando página {idx+1}...', compound='top',
                                 command=lambda i=idx: self._overview_jump(i))
            btn.pack(fill='both', expand=True)
            self.ttk.Label(holder, text=f'Página {idx+1}', anchor='center').pack(fill='x')
            self.overview_buttons[idx] = btn
            cached = self.overview_cache.get(item)
            if cached is not None:
                self._overview_display(idx, item, cached)
            else:
                to_render.append((idx, item))
        for c in range(4):
            self.overview_frame.columnconfigure(c, weight=1)
        for r in range(4):
            self.overview_frame.rowconfigure(r, weight=1)
        if not to_render:
            return

        def worker():
            try:
                with fitz.open(self.path) as source:
                    for idx, item in to_render:
                        if generation != self.overview_generation:
                            return
                        try:
                            if item.image_path is not None:
                                image = image_page_preview(item.image_path, 205, 155)
                            else:
                                page = source.load_page(item.source_index)
                                zoom = min(205 / page.rect.width, 155 / page.rect.height, 1.0)
                                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False,
                                                     colorspace=fitz.csRGB)
                                image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                            self.events.put(('overview_render', generation, idx, item, image, None))
                        except Exception as exc:
                            self.events.put(('overview_render', generation, idx, item, None, str(exc)))
            except Exception as exc:
                self.events.put(('overview_error', generation, str(exc)))
        self.overview_pool.submit(worker)

    def _overview_display(self, index: int, item: PageItem, image: Image.Image):
        from PIL import ImageTk
        button = self.overview_buttons.get(index)
        if button is None:
            return
        photo = ImageTk.PhotoImage(image)
        self.overview_photos[index] = photo
        button.configure(image=photo, text='', width=210, height=162)

    def _overview_jump(self, index: int):
        self.set_active(index)
        self._close_overview()

    def _show(self, pil: Image.Image):
        from PIL import ImageTk
        # Limita la memoria y evita retoques de una imagen al pasar de página.
        self.last_image = ImageTk.PhotoImage(pil)
        self.preview.configure(image=self.last_image, text='')
        self.state.set('Vista previa lista. Alt+← y Alt+→ cambian de página.')

    def _choose_image(self):
        from tkinter import filedialog
        file = filedialog.askopenfilename(parent=self.window, title='Fotografía para esta página',
            filetypes=[('Imágenes', '*.jpg *.jpeg *.png *.heic *.heif *.webp *.tif *.tiff *.bmp')])
        if not file:
            return None
        path = Path(file)
        try:
            from digitalizador import preview_image
            img, (w,h) = preview_image(path, 350)
            img.close()
            if min(w,h) < 800:
                from tkinter import messagebox
                messagebox.showwarning('Resolución insuficiente',
                    f'Esta foto tiene solo {w} × {h} píxeles. Selecciona una foto de mayor resolución.', parent=self.window)
                return None
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror('Imagen inválida', str(exc), parent=self.window)
            return None
        return path

    def _remember(self):
        self.history.append((list(self.pages), self.current()))
        self.undo_btn.state(['!disabled'])

    def undo(self):
        if not self.history or self.busy:
            return
        self.pages, index = self.history.pop()
        if not self.history:
            self.undo_btn.state(['disabled'])
        self._sync_list(min(index, len(self.pages)-1))

    def replace_photo(self):
        if self.busy:
            return
        photo = self._choose_image()
        if photo:
            current = self.current()
            self._remember()
            self.pages[current] = PageItem(image_path=photo)
            self.preview_cache.pop(PageItem(image_path=photo), None)
            self._sync_list(current)

    def insert_photo(self, after: bool):
        if self.busy:
            return
        photo = self._choose_image()
        if photo:
            index = self.current() + int(after)
            self._remember()
            self.pages.insert(index, PageItem(image_path=photo))
            self._sync_list(index)

    def save(self):
        from tkinter import filedialog, messagebox
        if self.busy:
            return
        if not changed_pages(self.pages, self.original_count):
            messagebox.showinfo('Sin cambios', 'Todavía no has insertado o reemplazado páginas.', parent=self.window)
            return
        name = self.path.stem + '_revisado.pdf'
        target = filedialog.asksaveasfilename(parent=self.window, title='Guardar PDF revisado',
            initialfile=name, initialdir=str(self.path.parent), defaultextension='.pdf',
            filetypes=[('Documento PDF','*.pdf')])
        if not target:
            return
        output = Path(target)
        if output.resolve() == self.path.resolve():
            messagebox.showerror('Proteger original', 'Elige otro nombre. El PDF original no se sobrescribe.', parent=self.window)
            return
        if output.exists():
            messagebox.showwarning('Archivo ya existente', 'Elige otro nombre. No se sobrescriben archivos anteriores.', parent=self.window)
            return
        self.busy = True
        self.save_btn.state(['disabled'])
        self.replace_btn.state(['disabled'])
        self.before_btn.state(['disabled'])
        self.after_btn.state(['disabled'])
        items = list(self.pages)
        self.state.set(f'Guardando {len(items)} páginas...')
        def worker():
            try:
                result = save_edited_pdf(self.path, items, output, lambda n, count: self.events.put(('progress', n, count)))
                self.events.put(('done', result))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        from tkinter import messagebox
        if not self.window.winfo_exists():
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == 'render':
                _, gen, item, im, err = event
                self.preview_pending.discard(item)
                if im is not None:
                    self.preview_cache[item] = im
                    self.preview_cache.move_to_end(item)
                    if len(self.preview_cache) > 12:
                        self.preview_cache.popitem(last=False)
                # Puede haberse iniciado como precarga: mostrar si sigue seleccionada.
                active = self.pages[self.current()] if self.pages else None
                if item == active and im is not None:
                    self._show(im)
                    self._prefetch_neighbors()
                elif item == active and err:
                    self.preview.configure(text=f'No se pudo mostrar: {err}', image='')
            elif event[0] == 'overview_render':
                _, gen, index, item, im, err = event
                if im is not None:
                    self.overview_cache[item] = im
                    self.overview_cache.move_to_end(item)
                    if len(self.overview_cache) > 64:
                        self.overview_cache.popitem(last=False)
                if gen == self.overview_generation and self.overview_window is not None:
                    if im is not None:
                        self._overview_display(index, item, im)
                    elif index in self.overview_buttons:
                        self.overview_buttons[index].configure(text=f'Página {index+1}: error')
            elif event[0] == 'overview_error':
                if event[1] == self.overview_generation:
                    self.state.set(f'No se pudieron cargar miniaturas: {event[2]}')
            elif event[0] == 'progress':
                self.state.set(f'Guardando página {event[1]} de {event[2]}...')
            elif event[0] == 'done':
                self.busy = False
                self.saved_pages = list(self.pages)
                self.state.set(f'Guardado: {event[1]["pages"]} páginas.')
                self._unlock()
                messagebox.showinfo('PDF revisado',
                    f'Archivo guardado y verificado.\n\n{event[1]["file"]}\n\n'
                    f'{event[1]["pages"]} páginas. Mantén el PDF original hasta revisar esta copia.', parent=self.window)
            elif event[0] == 'error':
                self.busy = False
                self._unlock()
                messagebox.showerror('No se pudo guardar', event[1], parent=self.window)
        self.window.after(80, self._poll)

    def _unlock(self):
        for b in (self.save_btn, self.replace_btn, self.before_btn, self.after_btn):
            b.state(['!disabled'])
        if self.history:
            self.undo_btn.state(['!disabled'])

    def close(self):
        from tkinter import messagebox
        if self.busy:
            messagebox.showinfo('Guardado activo', 'Termina el guardado antes de cerrar la ventana.', parent=self.window)
            return
        if self.pages != self.saved_pages:
            if not messagebox.askyesno('Cerrar sin guardar', '¿Cerrar esta ventana? Los cambios no guardados se perderán.', parent=self.window):
                return
        if self.overview_window is not None:
            self._close_overview()
        self.window.destroy()
        self.render_pool.shutdown(wait=False, cancel_futures=True)
        self.overview_pool.shutdown(wait=False, cancel_futures=True)


def open_editor(parent):
    from tkinter import filedialog, messagebox
    file = filedialog.askopenfilename(parent=parent, title='Abrir PDF para revisar',
        filetypes=[('Documentos PDF', '*.pdf')])
    if not file:
        return
    try:
        return PdfEditorWindow(parent, Path(file))
    except Exception as exc:
        messagebox.showerror('No se puede abrir el PDF', str(exc), parent=parent)
