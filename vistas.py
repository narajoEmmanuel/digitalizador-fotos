"""Vistas rápidas de revisión, sin modificar imágenes ni PDF.

Tkinter se usa únicamente en el hilo principal. Los renderizados se hacen en segundo plano.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue

import fitz
from PIL import Image, ImageTk


def render_pdf_page(path: Path, index: int, zoom: float, max_side: int = 5400) -> Image.Image:
    """Renderiza UNA página, limita RAM sin cambiar el archivo ni sus píxeles guardados."""
    with fitz.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("El PDF está protegido por contraseña.")
        if not 0 <= index < doc.page_count:
            raise IndexError("Página inexistente")
        page = doc.load_page(index)
        rect = page.rect
        scale = min(zoom, max_side / max(rect.width, rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


class PhotoMatrix:
    """Matriz de resultados previos al PDF, clic sobre una hoja abre sus 4 esquinas."""
    PAGE_SIZE = 16

    def __init__(self, parent, paths, preview_provider, on_edit):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.paths = list(paths)
        self.preview_provider = preview_provider
        self.on_edit = on_edit
        self.window = tk.Toplevel(parent)
        self.window.title("Revisar recortes en matriz")
        self.window.geometry("1050x770")
        self.window.minsize(710, 490)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.events = queue.Queue()
        self.generation = 0
        self.start = 0
        self.photos = {}
        self.buttons = {}
        self.closed = False
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill="both", expand=True)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="◀ 16 anteriores", command=lambda: self.show(self.start - 16)).pack(side="left")
        self.label = tk.StringVar()
        ttk.Label(bar, textvariable=self.label, font=("Segoe UI", 11, "bold")).pack(side="left", padx=12)
        ttk.Button(bar, text="16 siguientes ▶", command=lambda: self.show(self.start + 16)).pack(side="left")
        ttk.Label(frame, text="Pulsa una página para ajustar sus cuatro esquinas. Muestra el recorte previsto, sin alterar las fotos.").pack(anchor="w", pady=(0, 8))
        self.grid = ttk.Frame(frame)
        self.grid.pack(fill="both", expand=True)
        self.show(0)
        self.window.after(90, self.poll)

    def show(self, start):
        self.start = max(0, min(start, max(0, (len(self.paths)-1)//16*16)))
        self.generation += 1
        generation = self.generation
        for widget in self.grid.winfo_children():
            widget.destroy()
        self.buttons.clear()
        self.photos.clear()
        batch = list(enumerate(self.paths[self.start:self.start + self.PAGE_SIZE], self.start))
        self.label.set(f"Páginas {self.start+1} a {self.start+len(batch)} de {len(self.paths)}")
        for offset, (index, path) in enumerate(batch):
            r, c = divmod(offset, 4)
            cell = self.ttk.Frame(self.grid)
            cell.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
            button = self.tk.Button(cell, text="Cargando...", compound="top", bg="#E9EEF1",
                                    relief="flat", cursor="hand2", command=lambda i=index: self.choose(i))
            button.pack(fill="both", expand=True)
            self.ttk.Label(cell, text=f"Página {index+1}", anchor="center").pack(fill="x")
            self.buttons[index] = button
        for c in range(4):
            self.grid.columnconfigure(c, weight=1)
        for r in range(4):
            self.grid.rowconfigure(r, weight=1)

        def worker():
            for index, path in batch:
                if self.closed or generation != self.generation:
                    break
                try:
                    im = self.preview_provider(path)
                    im.thumbnail((214, 150), Image.Resampling.BILINEAR)
                    self.events.put((generation, index, im, None))
                except Exception as exc:
                    self.events.put((generation, index, None, str(exc)))
        self.pool.submit(worker)

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                generation, index, image, error = self.events.get_nowait()
            except queue.Empty:
                break
            if generation != self.generation or index not in self.buttons:
                continue
            if image is not None:
                photo = ImageTk.PhotoImage(image)
                self.photos[index] = photo
                self.buttons[index].configure(image=photo, text="")
            else:
                self.buttons[index].configure(text=f"Error: {error[:55]}")
        self.window.after(90, self.poll)

    def choose(self, index):
        self.close()
        self.on_edit(index)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.generation += 1
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.window.destroy()


class PdfZoomViewer:
    """Vista final del PDF real, página a página, zoom y pantalla completa."""
    def __init__(self, parent, pdf_path: Path, index: int = 0):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.path = Path(pdf_path)
        with fitz.open(self.path) as document:
            if document.needs_pass or not document.page_count:
                raise ValueError("No se puede abrir este PDF para revisión.")
            self.count = document.page_count
            self.page_sizes = [(p.rect.width, p.rect.height) for p in document]
        self.index = max(0, min(index, self.count - 1))
        self.zoom = 1.0
        self.fit = True
        self.fullscreen = False
        self.closed = False
        self.generation = 0
        self.render_after = None
        self.events = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.window = tk.Toplevel(parent)
        self.window.title(f"Vista final del PDF: {self.path.name}")
        self.window.geometry("1100x800")
        self.window.minsize(650, 420)
        if self.window.tk.call("tk", "windowingsystem") == "win32":
            self.window.state("zoomed")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        bar = ttk.Frame(self.window, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="◀", command=lambda: self.go(-1)).pack(side="left")
        self.page_label = tk.StringVar()
        ttk.Label(bar, textvariable=self.page_label, font=("Segoe UI", 11, "bold")).pack(side="left", padx=8)
        ttk.Button(bar, text="▶", command=lambda: self.go(1)).pack(side="left")
        ttk.Button(bar, text="Ajustar", command=self.fit_page).pack(side="left", padx=(18, 4))
        ttk.Button(bar, text="−", command=lambda: self.set_zoom(self.zoom/1.25)).pack(side="left")
        self.zoom_label = tk.StringVar()
        ttk.Label(bar, textvariable=self.zoom_label, width=9, anchor="center").pack(side="left")
        ttk.Button(bar, text="+", command=lambda: self.set_zoom(self.zoom*1.25)).pack(side="left")
        ttk.Button(bar, text="100 %", command=lambda: self.set_zoom(1.0)).pack(side="left", padx=4)
        ttk.Button(bar, text="Pantalla completa (F11)", command=self.toggle_fullscreen).pack(side="right")
        self.canvas = tk.Canvas(self.window, bg="#20252C", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        vs = ttk.Scrollbar(self.window, orient="vertical", command=self.canvas.yview)
        vs.pack(side="right", fill="y")
        hs = ttk.Scrollbar(self.window, orient="horizontal", command=self.canvas.xview)
        hs.pack(side="bottom", fill="x")
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.bind("<MouseWheel>", self.scroll)
        self.canvas.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(3, "units"))
        self.window.bind("<Left>", lambda _e: self.go(-1))
        self.window.bind("<Right>", lambda _e: self.go(1))
        self.window.bind("<Prior>", lambda _e: self.go(-1))
        self.window.bind("<Next>", lambda _e: self.go(1))
        self.window.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.window.bind("<Escape>", lambda _e: self.toggle_fullscreen() if self.fullscreen else self.close())
        self.window.bind("<Control-MouseWheel>", self.wheel_zoom)
        self.image_ref = None
        self.request()
        self.window.after(80, self.poll)

    def on_resize(self, _event):
        if self.fit and not self.closed:
            if self.render_after:
                self.window.after_cancel(self.render_after)
            self.render_after = self.window.after(180, self.request)

    def scroll(self, event):
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")

    def wheel_zoom(self, event):
        self.set_zoom(self.zoom * (1.25 if event.delta > 0 else .8))
        return "break"

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.window.attributes("-fullscreen", self.fullscreen)

    def fit_page(self):
        self.fit = True
        self.request()

    def set_zoom(self, zoom):
        self.fit = False
        self.zoom = max(.4, min(5.0, zoom))
        self.request()

    def go(self, offset):
        self.index = max(0, min(self.count - 1, self.index + offset))
        self.request()

    def request(self):
        if self.closed:
            return
        self.generation += 1
        token = self.generation
        w, h = self.page_sizes[self.index]
        effective_zoom = min((self.canvas.winfo_width()-28)/w,
                             (self.canvas.winfo_height()-28)/h) if self.fit else self.zoom
        effective_zoom = max(.15, min(5.0, effective_zoom))
        self.zoom_label.set(f"{round(effective_zoom * 100)} %")
        self.page_label.set(f"Página {self.index+1} de {self.count}")
        self.canvas.delete("all")
        self.canvas.create_text(50, 50, anchor="nw", fill="white", text="Cargando página...")
        index = self.index
        def worker():
            try:
                im = render_pdf_page(self.path, index, effective_zoom)
                self.events.put((token, im, None))
            except Exception as exc:
                self.events.put((token, None, str(exc)))
        self.pool.submit(worker)

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                token, im, error = self.events.get_nowait()
            except queue.Empty:
                break
            if token != self.generation:
                continue
            self.canvas.delete("all")
            if error:
                self.canvas.create_text(40, 40, anchor="nw", text=error, fill="white")
                continue
            self.image_ref = ImageTk.PhotoImage(im)
            w, h = im.size
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            x, y = max(0, (cw-w)//2), max(0, (ch-h)//2)
            self.canvas.create_image(x, y, anchor="nw", image=self.image_ref)
            self.canvas.configure(scrollregion=(0, 0, max(cw, w), max(ch, h)))
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        self.window.after(80, self.poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.generation += 1
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.window.destroy()
