"""Revisión previa a PDF: matriz, recorte, zoom, reemplazo e inserción."""
from pathlib import Path
from io import BytesIO
import queue
import numpy as np
from PIL import Image, ImageTk
from recorte import detectar_hoja, ordenar_esquinas, refinar_esquinas
from revisor_base import PhotoMatrix, validated_photo_corners


def final_export_preview(photo: Path, auto_crop: bool, corners=None,
                         rotation: int = 0) -> Image.Image:
    """Replica los píxeles y la codificación JPEG que se insertarán en el PDF.

    La vista no depende de una miniatura; parte de la foto original, realiza
    exactamente el mismo recorte a resolución completa y aplica calidad JPEG 97.
    """
    from digitalizador import prepare_page
    image, _cropped = prepare_page(
        photo, auto_crop=auto_crop, manual_corners=corners, rotation=rotation)
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
                 manual_corners, on_replace, on_insert, on_export, auto_crop=True,
                 pdf_name=None, rotations=None, on_rotate=None):
        self.mode = "preview"
        self.corners_enabled = False  # Preferencia para todas las hojas del revisor.
        self.dirty = False
        self.detect_steps = {}
        self.big_image = None
        self.big_photo = None
        self.full_preview = False
        self.full_pending_token = None
        self.big_token = 0
        self.big_events = queue.Queue()
        self.fit = True
        self.scale = 1.0
        self.pan_x = self.pan_y = 0.0
        self.drag_start = None
        self.on_replace, self.on_insert, self.on_export = on_replace, on_insert, on_export
        self.auto_crop = auto_crop
        self.pdf_name = pdf_name
        self.rotations = rotations if rotations is not None else {}
        self.on_rotate = on_rotate
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
        rotate_bar = ttk.Frame(self.controls)
        rotate_bar.pack(fill="x", pady=(4, 0), before=self.status_widget)
        ttk.Button(rotate_bar, text="↶ 90°", command=lambda: self.rotate(-90)).pack(
            side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(rotate_bar, text="90° ↷", command=lambda: self.rotate(90)).pack(
            side="left", fill="x", expand=True, padx=(3, 0))

        self.quality_label = self.tk.StringVar(value="")
        ttk.Label(self.controls, textvariable=self.quality_label).pack(
            fill="x", pady=(4, 0), before=self.status_widget)
        footer = ttk.Frame(self.controls)
        footer.pack(fill="x", pady=(5, 0), before=self.status_widget)
        if self.pdf_name is not None:
            name_row = ttk.Frame(footer)
            name_row.pack(fill="x")
            ttk.Label(name_row, text="Nombre").pack(side="left", padx=(0, 5))
            ttk.Entry(name_row, textvariable=self.pdf_name).pack(
                side="left", fill="x", expand=True)
        self.export_button = ttk.Button(footer, text="Exportar PDF", command=self.export)
        self.export_button.pack(fill="x", pady=(4, 0))
        self.detection_info = self.tk.StringVar(value="")
        ttk.Label(self.controls, textvariable=self.detection_info).pack(
            fill="x", before=self.status_widget)
        # Área independiente: no se borra al seleccionar otra miniatura.
        self.export_message = self.tk.StringVar(value="")
        self.export_message_label = ttk.Label(
            footer, textvariable=self.export_message, wraplength=310)
        self.export_message_label.pack(fill="x", pady=(5, 0))
        self.export_progress = ttk.Progressbar(
            footer, orient="horizontal", mode="determinate", maximum=100)
        self.export_progress.pack(fill="x", pady=(4, 0))
        self.export_progress.pack_forget()
        self.exported_file = None
        self.open_pdf_button = ttk.Button(footer, text="Abrir PDF", command=self.open_exported_pdf)
        self._set_mode_controls()
        self.status.set("")
        if self.paths:
            self.choose(0)
        self.window.after(100, self.poll_large)

    def set_auto_crop(self, enabled: bool):
        """Sincronizar el revisor abierto con la casilla de la pantalla principal."""
        if self.closed or self.auto_crop == enabled:
            return
        self.auto_crop = enabled
        self.detect_steps.clear()
        self.invalidate_all_previews()
        # No sobrescribir un recorte manual que aún no se ha guardado.
        if self.mode == "preview":
            self.preview_mode()
        elif self.selected is not None and not self.dirty:
            self.editor_loaded_index = None
            super().choose(self.selected)
        else:
            self.status.set("Recorte automático " +
                            ("activado" if enabled else "desactivado")
                            + ". Ajuste manual sin guardar conservado.")
        self._set_mode_controls()

    def set_batch_optimization_progress(self, done: int, total: int):
        """La matriz muestra el progreso global, su botón sigue siendo individual."""
        if not self.closed:
            self.detection_info.set(
                f"Optimizando lote: {done}/{total}" if done < total
                else f"Optimización completa: {total}/{total}")

    def refresh_auto_results(self):
        """Mostrar nuevos recortes conservando la edición actual sin guardar."""
        if self.closed:
            return
        self.detect_steps.clear()
        self.invalidate_all_previews()
        if self.selected is None:
            return
        if self.mode == "preview":
            self.preview_mode()
        elif not self.dirty and self.paths[self.selected] not in self.manual_corners:
            self.editor_loaded_index = None
            super().choose(self.selected)
        else:
            self.status.set("Optimización del lote finalizada. Se conserva el recorte manual.")
        self._set_mode_controls()

    def set_detection_progress(self, done: int, total: int):
        """Indicador breve que desaparece cuando el lote quedó analizado."""
        if total and done < total:
            self.detection_info.set(f"Preparando esquinas: {done}/{total}")
        else:
            self.detection_info.set("")

    def begin_export(self, target: Path, total: int):
        self.exported_file = None
        self.open_pdf_button.pack_forget()
        self.export_button.state(["disabled"])
        self.export_message_label.configure(foreground="#344054")
        self.export_message.set(f"Preparando {target.name} · 0/{total} páginas")
        self.export_progress.configure(mode="indeterminate")
        self.export_progress.pack(fill="x", pady=(4, 0))
        self.export_progress.start(12)

    def update_export_progress(self, done: int, total: int, elapsed: float = 0):
        from digitalizador import export_progress_details
        self.export_progress.stop()
        self.export_progress.configure(mode="determinate")
        # 95 % de barra como máximo mientras se generan páginas.
        # El texto indica porcentaje de páginas, no una duración garantizada.
        self.export_progress.configure(value=95 * done / max(1, total))
        self.export_message.set(export_progress_details(done, total, elapsed))

    def update_export_stage(self, stage: str):
        self.export_progress.stop()
        self.export_progress.configure(mode="indeterminate")
        self.export_progress.start(12)
        self.export_message.set("Verificando páginas del PDF..."
                                if stage == "verifying" else "Guardando PDF...")

    def finish_export(self, path: Path, pages: int, uncropped: int = 0):
        from digitalizador import export_success_text
        self.export_progress.stop()
        self.export_progress.configure(mode="determinate")
        self.export_progress.configure(value=100)
        self.exported_file = Path(path)
        self.export_button.state(["!disabled"])
        self.export_message_label.configure(
            foreground="#986300" if uncropped else "#18723D")
        self.export_message.set(export_success_text(Path(path), pages, uncropped))
        self.open_pdf_button.pack(fill="x", pady=(4, 0))
        self.window.bell()

    def fail_export(self, reason: str):
        self.export_progress.stop()
        self.export_progress.pack_forget()
        self.open_pdf_button.pack_forget()
        self.exported_file = None
        self.export_button.state(["!disabled"])
        self.export_message_label.configure(foreground="#B42318")
        self.export_message.set(f"✗ No se pudo exportar: {reason}")

    def open_exported_pdf(self):
        import os
        from tkinter import messagebox
        path = self.exported_file
        if path is None or not path.is_file():
            messagebox.showerror("PDF no disponible", "No se encuentra el PDF exportado.",
                                 parent=self.window)
            return
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror("No se pudo abrir", str(exc), parent=self.window)

    def _set_mode_controls(self):
        """El interruptor permanece visible y afecta a todas las páginas."""
        if self.mode == "preview":
            self.edit_button.configure(text="Activar esquinas")
            self.save_button.pack_forget()
            self.reset_button.pack_forget()
            self.board.configure(cursor="fleur")
        else:
            self.edit_button.configure(text="Desactivar esquinas")
            self.reset_button.configure(
                text=("Optimizar" if self.selected is not None
                      and self.detect_steps.get(self.paths[self.selected], 0)
                      else "Detectar"))
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
        """La geometría automática llega ya refinada, no debe redetectarse."""
        super()._load_editor(preview, size, detected)
        if (self.selected is not None and detected is not None
                and self.auto_crop
                and self.paths[self.selected] not in self.manual_corners):
            # El botón manual debe seguir optimizando, no regresar a la
            # primera detección que ya fue mejorada en segundo plano.
            self.detect_steps[self.paths[self.selected]] = 1
        self._set_mode_controls()

    def _page_caption(self, index):
        warning = self.crop_warnings.get(self.paths[index])
        return f"⚠ Página {index+1}" if warning else f"Página {index+1}"

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
        """Primera pulsación: detectar. Siguientes: optimizar el borde existente.

        El cálculo de OpenCV se realiza fuera del hilo de Tk.
        """
        if (self.mode != "edit" or self.editor_image is None
                or self.full_size is None or self.selected is None
                or self.editor_loaded_index != self.selected):
            return
        path = self.paths[self.selected]
        stage = self.detect_steps.get(path, 0)
        original = np.asarray(self.editor_image).copy()
        scale = np.float32([original.shape[1] / self.full_size[0],
                            original.shape[0] / self.full_size[1]])
        current = self.points.copy() * scale
        token, index = self.big_token, self.selected
        self.reset_button.state(["disabled"])
        self.status.set("Buscando mejores bordes..." if stage else "Detectando...")
        def detect():
            try:
                if stage:
                    found = refinar_esquinas(original, current)
                else:
                    from digitalizador import refine_automatic_corners
                    found = detectar_hoja(original)
                    if found is not None:
                        # La acción manual realiza el mismo doble refinamiento
                        # que el lote, no obliga a pulsar Detectar y Optimizar.
                        found = refine_automatic_corners(
                            original, found, max_passes=2)
                self.big_events.put(("detect", token, index, (stage, found), None))
            except Exception as exc:
                self.big_events.put(("detect", token, index, (stage, None), str(exc)))
        self.quick_pool.submit(detect)

    def _finish_detection(self, stage, found, error):
        """Aplicar solamente un recorte válido de la página actual."""
        self.reset_button.state(["!disabled"])
        path = self.paths[self.selected]
        if not stage:
            # La segunda pulsación intenta optimizar, no repetir la detección.
            self.detect_steps[path] = 1
        self._set_mode_controls()
        if error:
            self.status.set(f"No se pudo optimizar: {error}")
            return
        if found is None:
            self.status.set(
                "No encontré otro borde más fiable. Si ves un error, ajusta las esquinas manualmente."
                if stage else "No se detectaron esquinas. Puedes optimizar o ajustarlas.")
            return
        scale = np.float32([self.full_size[0] / self.editor_image.width,
                            self.full_size[1] / self.editor_image.height])
        points = ordenar_esquinas(found) * scale
        try:
            validated_photo_corners(points, self.full_size)
        except ValueError:
            self.status.set("Se descartó una geometría insegura.")
            return
        if self.points is not None and np.allclose(self.points, points, atol=2):
            self.status.set("No encontré un ajuste suficientemente seguro. Mantengo las esquinas.")
            return
        self.points = points.copy()
        self.detected_points = points.copy()
        self._draw_editor()
        self._edited()
        self.status.set(
            "Bordes refinados. Guarda el recorte si quedó bien."
            if stage else "Esquinas detectadas y optimizadas. Guarda el recorte.")

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
        # En modo global de esquinas se permanece editando para pasar a otra hoja.
        if self.corners_enabled:
            self.mode = "edit"
            self._set_mode_controls()
        else:
            self.preview_mode()
        self.status.set("Recorte guardado.")
        return True

    def choose(self, index):
        if self.closed or not 0 <= index < len(self.paths):
            return
        if self.selected is not None and self.selected != index and not self._pending():
            return
        self.mode = "edit" if self.corners_enabled else "preview"
        self._set_mode_controls()
        self.dirty = False
        self.big_token += 1
        self.full_pending_token = None
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        if self.mode == "edit":
            super().choose(index)
            self._set_mode_controls()
        else:
            # No cargar la foto a 1600 px ni detectarla de nuevo al hacer clic.
            # Basta la vista de 1050 px que alimenta la matriz.
            self.selected = index
            self.selection_token += 1
            self._highlight_selection()
            self.current_label.set(f"Página {index+1} de {len(self.paths)}")
            self.save_button.state(["disabled"])
            self.reset_button.state(["disabled"])
            self._show_quick_preview()

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
        # No usar la imagen/las esquinas de la página seleccionada anteriormente.
        if self.selected is not None:
            if self.editor_loaded_index != self.selected or self.editor_image is None:
                super().choose(self.selected)
            else:
                super()._draw_editor()

    def _show_quick_preview(self):
        """Vista ligera inmediata, sin lectura completa ni codificación JPEG."""
        if self.selected is None or self.mode != "preview" or self.closed:
            return
        index = self.selected
        token = self.big_token
        path = self.paths[index]
        self.board.delete("all")
        self.board.create_text(20, 20, text="Cargando...", fill="white", anchor="nw")
        self.quality_label.set("")
        issue = self.crop_warnings.get(path) if path not in self.manual_corners else None
        self.status.set(f"⚠ {issue}. Revisa esta hoja." if issue else "")
        with self.quick_lock:
            item = self.quick_cache.get(path)
            if item is not None:
                im, _warning = item
                self.quick_cache.move_to_end(path)
                quick = im.copy()
            else:
                quick = None
        if quick is not None:
            self._accept_quick_preview(quick)
        else:
            def load():
                try:
                    image, _warning = self.get_quick_preview(path)
                    self.big_events.put(("quick", token, index, image, None))
                except Exception as exc:
                    self.big_events.put(("quick", token, index, None, str(exc)))
            self.quick_pool.submit(load)

    def _accept_quick_preview(self, image):
        if self.big_image is not None:
            self.big_image.close()
        self.big_image = image
        self.full_preview = False
        self.fit = True
        self.pan_x = self.pan_y = 0
        self._draw_big()

    def _request_full_preview(self):
        """Solo procesar megapíxeles originales cuando el usuario pide zoom."""
        if (self.selected is None or self.mode != "preview" or self.closed
                or self.full_preview or self.full_pending_token == self.big_token):
            return
        index, token = self.selected, self.big_token
        photo = self.paths[index]
        corners = self.manual_corners.get(photo)
        if corners is not None:
            corners = corners.copy()
        rotation = self.rotations.get(photo, 0)
        self.full_pending_token = token
        self.quality_label.set("Cargando detalle original...")
        def load():
            try:
                img = final_export_preview(photo, auto_crop=self.auto_crop,
                                           corners=corners, rotation=rotation)
                self.big_events.put(("full", token, index, img, None))
            except Exception as exc:
                self.big_events.put(("full", token, index, None, str(exc)))
        self.quick_pool.submit(load)

    def preview_mode(self):
        self.mode = "preview"
        self._set_mode_controls()
        self.big_token += 1
        self.full_pending_token = None
        self._show_quick_preview()

    def poll_large(self):
        if self.closed:
            return
        while True:
            try:
                kind, token, index, im, error = self.big_events.get_nowait()
            except queue.Empty:
                break
            if kind == "detect":
                if (token == self.big_token and index == self.selected
                        and self.mode == "edit"
                        and self.editor_loaded_index == self.selected):
                    stage, corners = im
                    self._finish_detection(stage, corners, error)
                continue
            if token != self.big_token or index != self.selected or self.mode != "preview":
                if im is not None:
                    im.close()
                continue
            if error:
                if kind == "full":
                    self.full_pending_token = None
                self.status.set(f"No se pudo cargar: {error}")
                if im is not None:
                    im.close()
                continue
            if kind == "full":
                old = self.big_image
                if old is not None and not self.fit:
                    self.scale *= old.width / im.width
                self.big_image = im
                self.full_preview = True
                self.full_pending_token = None
                if old is not None:
                    old.close()
                self._draw_big()
            else:
                if self.full_preview:
                    im.close()
                else:
                    self._accept_quick_preview(im)
        self.window.after(70, self.poll_large)

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
        self.quality_label.set(
            resolution_info(image, scale) if self.full_preview else "Vista rápida · zoom para detalle real")

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
        self._request_full_preview()

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
        self._request_full_preview()

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

    def rotate(self, degrees: int):
        """Gira únicamente la página seleccionada, sin tocar la foto original."""
        from tkinter import messagebox
        if self.selected is None or self.on_rotate is None:
            return
        if not self._pending():
            return
        try:
            result = self.on_rotate(self.selected, degrees)
        except Exception as exc:
            messagebox.showerror("No se pudo girar", str(exc), parent=self.window)
            return
        self.refresh_item(self.selected)
        # Los puntos de recorte siguen en coordenadas de la foto original.
        # Mostrar la página final girada, no un editor de esquinas desorientado.
        self.corners_enabled = False
        self.preview_mode()
        self.status.set(f"Giro: {result}°")

    def replace(self):
        if self.selected is None or not self._pending():
            return
        path = self._file_dialog()
        if path is None:
            return
        index = self.selected
        self.discard_quick_preview(self.paths[index])
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
            self.on_export(self)

    def close(self):
        self.big_token += 1
        if self.big_image is not None:
            self.big_image.close()
            self.big_image = None
        super().close()
