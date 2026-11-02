"""Revisión previa a PDF: matriz, recorte, zoom, reemplazo e inserción."""
from pathlib import Path
import queue
from PIL import Image, ImageTk
from vistas import PhotoMatrix, validated_photo_corners


class ReviewWorkspace(PhotoMatrix):
    """Matriz y edición continua, antes de exportar el documento definitivo."""

    def __init__(self, parent, paths, preview_provider, on_save, photo_loader,
                 manual_corners, on_replace, on_insert, on_export, auto_crop=True):
        self.mode = "edit"
        self.dirty = False
        self.approved = set()
        self.big_image = None
        self.big_photo = None
        self.big_token = 0
        self.big_events = queue.Queue()
        self.fit = True
        self.scale = 1.0
        self.pan_x = self.pan_y = 0.0
        self.drag_start = None
        self.on_replace, self.on_insert, self.on_export = on_replace, on_insert, on_export
        self.auto_crop = auto_crop
        super().__init__(parent, paths, preview_provider, on_save, photo_loader, manual_corners)
        from tkinter import ttk
        self.window.title("Revisar hojas antes de exportar PDF")
        self.board.bind("<ButtonPress-1>", self._press)
        self.board.bind("<B1-Motion>", self._drag)
        self.board.bind("<ButtonRelease-1>", lambda _event: setattr(self, "drag_start", None))
        self.board.bind("<MouseWheel>", self._wheel)
        self.board.bind("<Button-4>", lambda _event: self._scroll(-1))
        self.board.bind("<Button-5>", lambda _event: self._scroll(1))
        right = self.board.master
        tools = ttk.Frame(right)
        tools.pack(before=self.board, fill="x", pady=(0, 6))
        ttk.Button(tools, text="Editar esquinas", command=self.edit_mode).pack(side="left")
        ttk.Button(tools, text="Vista ampliada", command=self.preview_mode).pack(side="left", padx=5)
        ttk.Button(tools, text="Ajustar", command=self.fit_zoom).pack(side="left")
        ttk.Button(tools, text="100 %", command=lambda: self.set_zoom(1.0)).pack(side="left")
        ttk.Button(tools, text="−", command=lambda: self.zoom_by(.8)).pack(side="left")
        ttk.Button(tools, text="+", command=lambda: self.zoom_by(1.25)).pack(side="left")
        changes = ttk.Frame(right)
        changes.pack(before=self.board, fill="x", pady=(0, 6))
        ttk.Button(changes, text="Sustituir foto", command=self.replace).pack(side="left")
        ttk.Button(changes, text="Insertar antes", command=lambda: self.insert(False)).pack(side="left", padx=5)
        ttk.Button(changes, text="Insertar después", command=lambda: self.insert(True)).pack(side="left")
        ttk.Button(changes, text="Aprobar ✓", command=self.approve).pack(side="right")
        footer = ttk.Frame(right)
        footer.pack(before=self.board, fill="x", pady=(0, 6))
        ttk.Button(footer, text="Exportar PDF después de revisar", command=self.export).pack(side="right")
        self.approval_label = self.tk.StringVar(value=f"0 de {len(self.paths)} hojas aprobadas")
        ttk.Label(footer, textvariable=self.approval_label).pack(side="left")
        if self.paths:
            self.choose(0)
        self.window.after(100, self.poll_large)

    def _page_caption(self, index):
        return f"Página {index+1}" + (" ✓" if self.paths[index] in self.approved else "")

    def _edited(self):
        if self.selected is not None:
            self.dirty = True
            self.approved.discard(self.paths[self.selected])
            self._highlight_selection()

    def _press(self, event):
        if self.mode == "preview":
            self.drag_start = (event.x, event.y, self.pan_x, self.pan_y)
        else:
            super()._press(event)

    def _drag(self, event):
        if self.mode == "preview":
            if self.drag_start:
                x, y, px, py = self.drag_start
                self.pan_x, self.pan_y = px - event.x + x, py - event.y + y
                self._draw_big()
        else:
            prior = self.drag_index
            super()._drag(event)
            if prior is not None:
                self._edited()

    def reset(self):
        super().reset()
        self._edited()

    def save(self):
        from tkinter import messagebox
        if self.selected is None or self.points is None:
            return False
        try:
            points = validated_photo_corners(self.points, self.full_size)
            self.on_save(self.selected, points.copy())
        except Exception as exc:
            messagebox.showwarning("No se pudo guardar", str(exc), parent=self.window)
            return False
        self.dirty = False
        self.saved_indices.add(self.selected)
        self.refresh_item(self.selected)
        self._highlight_selection()
        self.status.set(f"✓ Recorte guardado en página {self.selected+1}. La matriz sigue abierta.")
        return True

    def choose(self, index):
        if self.selected is not None and self.selected != index and self.dirty:
            from tkinter import messagebox
            answer = messagebox.askyesnocancel("Recorte pendiente",
                     "¿Guardar las esquinas antes de cambiar de página?", parent=self.window)
            if answer is None or (answer and not self.save()):
                return
        self.mode = "edit"
        self.dirty = False
        self.big_token += 1
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        super().choose(index)

    def _draw_editor(self):
        if self.mode == "preview":
            self._draw_big()
        else:
            super()._draw_editor()

    def edit_mode(self):
        self.mode = "edit"
        self.big_token += 1
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        super()._draw_editor()

    def preview_mode(self):
        if self.selected is None or self.points is None:
            return
        from tkinter import messagebox
        try:
            points = validated_photo_corners(self.points, self.full_size)
        except ValueError as exc:
            messagebox.showwarning("Recorte incorrecto", str(exc), parent=self.window)
            return
        self.mode = "preview"
        self.big_token += 1
        token, index = self.big_token, self.selected
        photo = self.paths[index]
        quad = points.copy() if self.dirty or photo in self.manual_corners else None
        self.board.delete("all")
        self.board.create_text(25, 25, text="Preparando vista a resolución real...", fill="white", anchor="nw")
        self.status.set("Vista previa antes del PDF, procesada desde la foto original")
        def load():
            try:
                from digitalizador import prepare_page
                im, _cropped = prepare_page(photo, auto_crop=self.auto_crop,
                    manual_corners=quad if self.auto_crop else None)
                self.big_events.put((token, index, im, None))
            except Exception as exc:
                self.big_events.put((token, index, None, str(exc)))
        self.pool.submit(load)

    def poll_large(self):
        if self.closed:
            return
        while True:
            try:
                token, index, im, error = self.big_events.get_nowait()
            except queue.Empty:
                break
            if token != self.big_token or index != self.selected or self.mode != "preview":
                if im is not None:
                    im.close()
                continue
            if error:
                self.status.set(f"No se pudo ampliar la hoja: {error}")
            else:
                if self.big_image is not None:
                    self.big_image.close()
                self.big_image = im
                self.fit = True
                self.pan_x = self.pan_y = 0
                self._draw_big()
        self.window.after(100, self.poll_large)

    def _draw_big(self):
        if self.closed or self.mode != "preview" or self.big_image is None:
            return
        image = self.big_image
        width, height = max(50, self.board.winfo_width()), max(50, self.board.winfo_height())
        scale = min(width/image.width, height/image.height) if self.fit else self.scale
        scale = max(.01, scale)
        w, h = image.width * scale, image.height * scale
        self.pan_x = max(0, min(self.pan_x, max(0, w-width)))
        self.pan_y = max(0, min(self.pan_y, max(0, h-height)))
        box = (int(self.pan_x/scale), int(self.pan_y/scale),
               min(image.width, int((self.pan_x+min(w,width))/scale)+1),
               min(image.height, int((self.pan_y+min(h,height))/scale)+1))
        crop = image.crop(box)
        size = (max(1, int(crop.width*scale)), max(1, int(crop.height*scale)))
        if crop.size != size:
            crop = crop.resize(size, Image.Resampling.BILINEAR)
        self.big_photo = ImageTk.PhotoImage(crop)
        crop.close()
        self.board.delete("all")
        self.board.create_image(max(0, (width-size[0])//2), max(0, (height-size[1])//2),
                                anchor="nw", image=self.big_photo)

    def fit_zoom(self):
        self.fit = True
        self.pan_x = self.pan_y = 0
        self._draw_big()

    def set_zoom(self, value):
        self.fit = False
        self.scale = max(.2, min(3.0, value))
        self.pan_x = self.pan_y = 0
        self._draw_big()

    def zoom_by(self, factor):
        if self.mode != "preview" or self.big_image is None:
            return
        if self.fit:
            self.scale = min(self.board.winfo_width()/self.big_image.width,
                             self.board.winfo_height()/self.big_image.height)
        self.set_zoom(self.scale*factor)

    def _scroll(self, sign):
        if self.mode == "preview":
            self.pan_y += sign * 100
            self._draw_big()

    def _wheel(self, event):
        if self.mode == "preview":
            self._scroll(-1 if event.delta > 0 else 1)
            return "break"

    def _file_dialog(self):
        from tkinter import filedialog, messagebox
        from digitalizador import EXTENSIONS
        file = filedialog.askopenfilename(parent=self.window, title="Elegir fotografía",
             filetypes=[("Fotografías", "*.jpg *.jpeg *.png *.heic *.heif *.webp *.tif *.tiff *.bmp"),
                        ("Todos los archivos", "*.*")])
        if not file:
            return None
        path = Path(file)
        if path.suffix.lower() not in EXTENSIONS or not path.is_file():
            messagebox.showwarning("Archivo incorrecto", "Selecciona una fotografía compatible.", parent=self.window)
            return None
        if path in self.paths:
            messagebox.showwarning("Foto repetida", "La fotografía ya está en este documento.", parent=self.window)
            return None
        return path

    def _pending(self):
        if not self.dirty:
            return True
        from tkinter import messagebox
        answer = messagebox.askyesnocancel("Recorte pendiente", "¿Guardar el recorte antes de continuar?", parent=self.window)
        return False if answer is None else (self.save() if answer else True)

    def replace(self):
        if self.selected is None or not self._pending():
            return
        path = self._file_dialog()
        if path is None:
            return
        index, old = self.selected, self.paths[self.selected]
        self.on_replace(index, path)
        self.paths[index] = path
        self.approved.discard(old)
        self.saved_indices.discard(index)
        self.dirty = False
        self.show(index//16*16)
        self.choose(index)
        self._update_count()
        self.status.set(f"Página {index+1} sustituida; revisa la nueva fotografía antes de aprobar")

    def insert(self, after):
        if self.selected is None or not self._pending():
            return
        path = self._file_dialog()
        if path is None:
            return
        index = self.selected + int(after)
        self.on_insert(index, path)
        self.paths.insert(index, path)
        self.saved_indices = {i + (i >= index) for i in self.saved_indices}
        self.dirty = False
        self.show(index//16*16)
        self.choose(index)
        self._update_count()
        self.status.set(f"Página {index+1} insertada sin reordenar las demás")

    def _update_count(self):
        self.approval_label.set(f"{len(self.approved)} de {len(self.paths)} hojas aprobadas")

    def approve(self):
        if self.selected is None:
            return
        if self.dirty and not self.save():
            return
        self.approved.add(self.paths[self.selected])
        self._highlight_selection()
        self._update_count()
        self.status.set(f"✓ Página {self.selected+1} aprobada, puedes seguir revisando")

    def export(self):
        from tkinter import messagebox
        if not self.paths or not self._pending():
            return
        missing = len(self.paths) - len(self.approved)
        if missing and not messagebox.askyesno("Confirmar exportación",
            f"Todavía hay {missing} hoja(s) sin marcar como aprobadas. ¿Exportar igualmente?",
            parent=self.window):
            return
        self.on_export()

    def close(self):
        self.big_token += 1
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        super().close()
