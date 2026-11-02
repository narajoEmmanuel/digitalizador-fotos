"""Revisión previa a PDF: matriz, recorte, zoom, reemplazo e inserción."""
from pathlib import Path
from io import BytesIO
import queue
import numpy as np
from PIL import Image, ImageTk
from recorte import detectar_hoja, ordenar_esquinas
from revisor_base import PhotoMatrix, validated_photo_corners


def final_export_preview(photo: Path, auto_crop: bool, corners=None) -> Image.Image:
    """Replica los píxeles y la codificación JPEG que se insertarán en el PDF.

    La vista no depende de una miniatura; parte de la foto original, realiza
    exactamente el mismo recorte a resolución completa y aplica calidad JPEG 97.
    """
    from digitalizador import prepare_page
    image, _cropped = prepare_page(photo, auto_crop=auto_crop, manual_corners=corners)
    try:
        with BytesIO() as buffer:
            image.save(buffer, "JPEG", quality=97, subsampling=0, optimize=True)
            buffer.seek(0)
            with Image.open(buffer) as decoded:
                decoded.load()
                return decoded.convert("RGB").copy()
    finally:
        image.close()


def resolution_info(image: Image.Image, scale: float) -> str:
    """La escala 1.0 corresponde a un píxel real por píxel de pantalla."""
    w, h = image.size
    return f"{w:,} × {h:,} px   ·   {scale*100:.0f} %"



class ReviewWorkspace(PhotoMatrix):
    """Matriz y edición continua, antes de exportar el documento definitivo."""

    def __init__(self, parent, paths, preview_provider, on_save, photo_loader,
                 manual_corners, on_replace, on_insert, on_export, auto_crop=True):
        self.mode = "preview"
        self.corners_enabled = False  # Preferencia para todas las hojas del revisor.
        self.dirty = False
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
        self.window.title("Revisión de páginas")
        self.board.bind("<ButtonPress-1>", self._press)
        self.board.bind("<B1-Motion>", self._drag)
        self.board.bind("<ButtonRelease-1>", lambda _event: setattr(self, "drag_start", None))
        self.board.bind("<MouseWheel>", self._wheel)
        self.board.bind("<Button-4>", lambda _event: self._scroll(-1))
        self.board.bind("<Button-5>", lambda _event: self._scroll(1))
        # Controles debajo de las miniaturas, nunca sobre la vista ampliada.
        tools = self.action_bar
        self.edit_button = ttk.Button(tools, text="Activar esquinas", command=self.toggle_corners)
        self.edit_button.pack(side="left")
        self.save_button.configure(text="Guardar recorte")
        self.reset_button.configure(text="Detectar", command=self.reset)
        self.board.bind("<Double-Button-1>", self._double_click)
        self.board.bind("<Configure>", self._resize)

        changes = ttk.Frame(self.controls)
        changes.pack(fill="x", pady=(5, 0), before=self.status_widget)
        ttk.Button(changes, text="Sustituir", command=self.replace).pack(side="left")
        ttk.Button(changes, text="+ Antes", command=lambda: self.insert(False)).pack(side="left", padx=5)
        ttk.Button(changes, text="+ Después", command=lambda: self.insert(True)).pack(side="left")

        self.quality_label = self.tk.StringVar(value="")
        ttk.Label(self.controls, textvariable=self.quality_label).pack(
            fill="x", pady=(4, 0), before=self.status_widget)
        footer = ttk.Frame(self.controls)
        footer.pack(fill="x", pady=(6, 0))
        ttk.Button(footer, text="Exportar PDF", command=self.export).pack(side="right")
        self._set_mode_controls()
        self.status.set("")
        if self.paths:
            self.choose(0)
        self.window.after(100, self.poll_large)

    def _set_mode_controls(self):
        """El interruptor permanece visible y afecta a todas las páginas."""
        if self.mode == "preview":
            self.edit_button.configure(text="Activar esquinas")
            self.save_button.pack_forget()
            self.reset_button.pack_forget()
            self.board.configure(cursor="fleur")
        else:
            self.edit_button.configure(text="Desactivar esquinas")
            self.reset_button.pack(side="right")
            self.save_button.pack(side="right", padx=5)
            self.board.configure(cursor="crosshair")

    def toggle_corners(self):
        """Activa o desactiva el ajuste manual persistente entre páginas."""
        if self.corners_enabled:
            if not self._pending():
                return
            self.corners_enabled = False
            self.preview_mode()
        else:
            self.corners_enabled = True
            self.edit_mode()

    def _double_click(self, _event):
        if self.mode == "preview":
            self.fit_zoom()
            return "break"

    def _load_editor(self, preview, size, detected):
        """Mostrar la imagen exportable al cargar cada miniatura, no las esquinas."""
        super()._load_editor(preview, size, detected)
        if self.mode == "preview":
            self.preview_mode()

    def _page_caption(self, index):
        return f"Página {index+1}"

    def _edited(self):
        if self.selected is not None:
            self.dirty = True

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
        """Recalcular el contorno, indicando si la detección es imposible o igual."""
        if self.mode != "edit" or self.editor_image is None or self.full_size is None:
            return
        detected = detectar_hoja(np.asarray(self.editor_image))
        if detected is None:
            self.status.set("No se detectaron esquinas. Ajusta el recorte manualmente.")
            return
        scale = np.float32([self.full_size[0] / self.editor_image.width,
                            self.full_size[1] / self.editor_image.height])
        points = ordenar_esquinas(detected) * scale
        if self.points is not None and np.allclose(self.points, points, atol=2):
            self.status.set("El recorte automático no cambió.")
            return
        self.detected_points = points.copy()
        self.points = points.copy()
        self._draw_editor()
        self._edited()
        self.status.set("Recorte actualizado. Comprueba las esquinas.")

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
        self.auto_crop = True
        self.saved_indices.add(self.selected)
        self.refresh_item(self.selected)
        self._highlight_selection()
        # En modo global de esquinas se permanece editando para pasar a otra hoja.
        if self.corners_enabled:
            self.mode = "edit"
            self._set_mode_controls()
        else:
            self.preview_mode()
        self.status.set("Recorte guardado.")
        return True

    def choose(self, index):
        if self.selected is not None and self.selected != index and not self._pending():
            return
        # Nunca desactivar la herramienta al seleccionar otra miniatura.
        self.mode = "edit" if getattr(self, "corners_enabled", False) else "preview"
        self._set_mode_controls()
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
        self._set_mode_controls()
        self.status.set("")
        self.big_token += 1
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        if self.selected is not None and self.editor_image is not None:
            super()._draw_editor()

    def preview_mode(self):
        # También debe poder apagarse mientras se carga otra hoja.
        self.mode = "preview"
        self._set_mode_controls()
        if self.selected is None or self.editor_image is None:
            return
        from tkinter import messagebox
        photo = self.paths[self.selected]
        quad = None
        if self.dirty or photo in self.manual_corners:
            try:
                quad = validated_photo_corners(self.points, self.full_size).copy()
            except ValueError as exc:
                messagebox.showwarning("Recorte incorrecto", str(exc), parent=self.window)
                return
        self.mode = "preview"
        self._set_mode_controls()
        self.big_token += 1
        token, index = self.big_token, self.selected
        self.board.delete("all")
        self.board.create_text(25, 25, text="Cargando...", fill="white", anchor="nw")
        self.quality_label.set("")
        self.status.set("Recorte sin guardar" if self.dirty else "")
        def load():
            try:
                im = final_export_preview(photo, auto_crop=self.auto_crop,
                    corners=quad if self.auto_crop else None)
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
                self.status.set(f"No se pudo mostrar la calidad final: {error}")
                self.quality_label.set("")
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
        self.quality_label.set(resolution_info(image, scale))

    def fit_zoom(self):
        self.fit = True
        self.pan_x = self.pan_y = 0
        self._draw_big()

    def set_zoom(self, value):
        if self.mode != "preview" or self.big_image is None:
            return
        self.fit = False
        self.scale = max(.15, min(5.0, float(value)))
        self.pan_x = self.pan_y = 0
        self._draw_big()

    def zoom_by(self, factor, anchor=None):
        """Aproximar alrededor del ratón, manteniendo la zona inspeccionada."""
        if self.mode != "preview" or self.big_image is None:
            return
        im = self.big_image
        width, height = max(50, self.board.winfo_width()), max(50, self.board.winfo_height())
        previous = min(width/im.width, height/im.height) if self.fit else self.scale
        next_scale = max(.15, min(5.0, previous * factor))
        if abs(next_scale - previous) < 1e-6:
            return
        cx, cy = anchor if anchor is not None else (width / 2, height / 2)
        old_offset_x = max(0, (width-im.width*previous)/2)
        old_offset_y = max(0, (height-im.height*previous)/2)
        source_x = (self.pan_x + cx-old_offset_x) / previous
        source_y = (self.pan_y + cy-old_offset_y) / previous
        new_offset_x = max(0, (width-im.width*next_scale)/2)
        new_offset_y = max(0, (height-im.height*next_scale)/2)
        self.pan_x = max(0, source_x*next_scale-cx+new_offset_x)
        self.pan_y = max(0, source_y*next_scale-cy+new_offset_y)
        self.fit = False
        self.scale = next_scale
        self._draw_big()

    def _scroll(self, sign):
        if self.mode == "preview":
            self.zoom_by(1.12 if sign < 0 else 1/1.12)

    def _wheel(self, event):
        if self.mode == "preview":
            self.zoom_by(1.12 if event.delta > 0 else 1/1.12, (event.x, event.y))
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
        if answer is None:
            return False
        if answer:
            return self.save()
        # Descartar sin mostrar después esquinas que no se guardaron.
        photo = self.paths[self.selected]
        saved = self.manual_corners.get(photo)
        if saved is not None:
            self.points = saved.copy()
        elif self.detected_points is not None:
            self.points = self.detected_points.copy()
        elif self.full_size is not None:
            w, h = self.full_size
            self.points = np.float32([[w*.05, h*.05], [w*.95, h*.05],
                                      [w*.95, h*.95], [w*.05, h*.95]])
        self.dirty = False
        return True

    def replace(self):
        if self.selected is None or not self._pending():
            return
        path = self._file_dialog()
        if path is None:
            return
        index = self.selected
        self.on_replace(index, path)
        self.paths[index] = path
        self.saved_indices.discard(index)
        self.dirty = False
        self.show(index//16*16)
        self.choose(index)
        self.status.set(f"Página {index+1} sustituida.")

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
        self.status.set(f"Página {index+1} insertada.")

    def export(self):
        # La revisión visual de la matriz es voluntaria. Ninguna aprobación
        # individual es necesaria para crear el PDF.
        if self.paths and self._pending():
            self.on_export()

    def close(self):
        self.big_token += 1
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        super().close()
