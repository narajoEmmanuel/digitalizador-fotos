"""Digitalizador de fotografías a PDF, sin OCR ni transcripción.

Compatible con Windows 10/11, Python 3.10+.
El programa conserva el color y nunca modifica las fotografías originales.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import queue
import re
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Callable

from recorte import detectar_hoja, ordenar_esquinas

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageCms, ImageOps, ImageTk
from reportlab.pdfgen import canvas

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
MAX_SIDE = 3000  # Detalle de calidad para archivo, sin archivos innecesariamente gigantes.


def capture_datetime(photo: Path) -> datetime:
    """Obtiene la fecha ORIGINAL de toma (EXIF DateTimeOriginal), no la del archivo.

    No se usan nombres, fechas de descarga ni modificaciones de OneDrive.
    El offset horario y fracciones de segundo se conservan cuando existen.
    """
    try:
        with Image.open(photo) as image:
            exif = image.getexif()
            camera_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            raw = camera_ifd.get(36867) or exif.get(36867)  # DateTimeOriginal
            subsec = camera_ifd.get(37521) or exif.get(37521)  # SubSecTimeOriginal
            offset = camera_ifd.get(36881) or exif.get(36881)  # OffsetTimeOriginal
    except Exception as exc:
        raise ValueError(f"{photo.name}: no se pudieron leer sus metadatos de captura ({exc}).") from exc

    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    if not isinstance(raw, str):
        raise ValueError(
            f"{photo.name}: falta EXIF DateTimeOriginal. Exporta la foto original "
            "desde el iPhone/OneDrive sin eliminar metadatos; no se usará la fecha de subida."
        )
    try:
        result = datetime.strptime(raw.strip().strip("\x00"), "%Y:%m:%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"{photo.name}: hora EXIF DateTimeOriginal no válida: {raw!r}.") from exc

    if isinstance(subsec, bytes):
        subsec = subsec.decode("ascii", errors="replace")
    if subsec is not None:
        digits = str(subsec).strip().strip("\x00")
        if digits.isdigit():
            result = result.replace(microsecond=int((digits + "000000")[:6]))

    if isinstance(offset, bytes):
        offset = offset.decode("ascii", errors="replace")
    if isinstance(offset, str):
        match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset.strip().strip("\x00"))
        if match:
            hours, minutes = int(match[2]), int(match[3])
            if hours <= 23 and minutes <= 59:
                delta = timedelta(hours=hours, minutes=minutes)
                result = result.replace(tzinfo=timezone(delta if match[1] == "+" else -delta))
    return result


def capture_order(paths: list[Path]) -> list[Path]:
    """Orden estricto por captura; si faltan metadatos, no adivina el orden."""
    dates = []
    failures = []
    for photo in paths:
        try:
            dates.append((photo, capture_datetime(photo)))
        except ValueError as exc:
            failures.append(str(exc))
    if failures:
        sample = "\n".join(f"- {message}" for message in failures[:8])
        remaining = f"\n... y {len(failures) - 8} más." if len(failures) > 8 else ""
        raise ValueError(
            f"{len(failures)} foto(s) sin fecha original de captura válida. "
            "No se creará el PDF con un orden supuesto.\n" + sample + remaining
        )
    # Si TODAS las fotos tienen zona horaria, comparar instantes absolutos en UTC.
    # Si algunas no la incluyen, comparar la hora local registrada por la cámara.
    all_zoned = all(timestamp.tzinfo is not None for _, timestamp in dates)
    dates.sort(key=lambda item: item[1].astimezone(timezone.utc)
               if all_zoned else item[1].replace(tzinfo=None))
    # Empates exactos conservan el orden de entrada: EXIF no permite distinguirlos.
    return [path for path, _ in dates]


def discover_images(folder: Path) -> list[Path]:
    photos = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS]
    return capture_order(photos)


def open_color_image(path: Path) -> Image.Image:
    if path.suffix.lower() in {".heic", ".heif"} and not HEIC_AVAILABLE:
        raise RuntimeError("Para abrir fotos HEIC instala pillow-heif: pip install pillow-heif")
    with Image.open(path) as source:
        source.load()
        corrected = ImageOps.exif_transpose(source)
        icc = corrected.info.get("icc_profile")
        # Si la imagen es Display P3, convertirla a sRGB conserva su aspecto en lectores PDF.
        if icc:
            try:
                from io import BytesIO
                corrected = ImageCms.profileToProfile(
                    corrected.convert("RGB"), ImageCms.ImageCmsProfile(BytesIO(icc)), ImageCms.createProfile("sRGB"),
                    outputMode="RGB",
                )
            except Exception:
                corrected = corrected.convert("RGB")
        else:
            corrected = corrected.convert("RGB")
        return corrected.copy()


def find_document_corners(rgb: np.ndarray) -> np.ndarray | None:
    """Encuentra la hoja usando bordes, contraste y color del fondo."""
    return detectar_hoja(rgb)


def prepare_page(
    photo: Path, auto_crop: bool = True, manual_corners: np.ndarray | None = None,
) -> tuple[Image.Image, bool]:
    """Imagen RGB, sin filtros ni OCR. Retorna (imagen, recortada)."""
    pil = open_color_image(photo)
    image = np.asarray(pil)
    cropped = False
    if auto_crop:
        corners = manual_corners if manual_corners is not None else find_document_corners(image)
        if corners is not None:
            corners = ordenar_esquinas(corners)
            tl, tr, br, bl = corners
            width = int(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl)))
            height = int(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr)))
            if width >= 100 and height >= 100:
                scale = min(1.0, MAX_SIDE / max(width, height))
                out_w, out_h = max(1, round(width*scale)), max(1, round(height*scale))
                dest = np.float32([[0, 0], [out_w-1, 0], [out_w-1, out_h-1], [0, out_h-1]])
                transform = cv2.getPerspectiveTransform(corners.astype(np.float32), dest)
                result = cv2.warpPerspective(image, transform, (out_w, out_h), flags=cv2.INTER_CUBIC)
                pil = Image.fromarray(result, "RGB")
                cropped = True
    if not cropped and max(pil.size) > MAX_SIDE:
        pil.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return pil, cropped


def fit_on_page(image_file: Path, pdf: canvas.Canvas):
    """El PDF ocupa solo el área recortada, sin bordes blancos artificiales."""
    with Image.open(image_file) as img:
        w, h = img.size
    # Tamaño de página según la relación de aspecto real del recorte.
    # La anchura es equivalente a A4, sin obligar a páginas con márgenes.
    page_w = 595.28 if w <= h else 841.89
    page_h = page_w * h / w
    pdf.setPageSize((page_w, page_h))
    pdf.drawImage(str(image_file), 0, 0, width=page_w, height=page_h)
    pdf.showPage()


def create_pdf(
    paths: list[Path], target: Path, auto_crop: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    manual_corners: dict[Path, np.ndarray] | None = None,
) -> dict:
    if not paths:
        raise ValueError("La carpeta no contiene fotografías compatibles.")
    paths = capture_order(paths)  # Garantiza el orden EXIF incluso desde la consola o la API.
    target.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    errors: list[str] = []
    written = 0
    with tempfile.TemporaryDirectory(prefix="digitalizador_") as temp_dir:
        with tempfile.NamedTemporaryFile(
            prefix=".digitalizador_", suffix=".pdf", dir=target.parent, delete=False
        ) as pdf_temp:
            temp_pdf = Path(pdf_temp.name)
        try:
            pdf = canvas.Canvas(str(temp_pdf), pagesize=(595.28, 841.89), pageCompression=1)
            pdf.setTitle(target.stem)
            pdf.setAuthor("Digitalizador de fotos")
            pdf.setSubject("Documento digitalizado desde fotografías, sin OCR")
            for i, path in enumerate(paths, 1):
                try:
                    result, cropped = prepare_page(
                        path, auto_crop=auto_crop,
                        manual_corners=(manual_corners or {}).get(path),
                    )
                    filename = Path(temp_dir) / f"pagina_{i:06d}.jpg"
                    result.save(filename, "JPEG", quality=94, subsampling=0, optimize=True)
                    result.close()
                    fit_on_page(filename, pdf)
                    written += 1
                    if auto_crop and not cropped:
                        warnings.append(path.name)
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
                finally:
                    if progress:
                        progress(i, len(paths), path.name)
            if written == 0:
                raise RuntimeError("No se pudo procesar ninguna imagen. " + "; ".join(errors[:3]))
            pdf.save()
            os.replace(temp_pdf, target)
        finally:
            if temp_pdf.exists():
                temp_pdf.unlink()
    return {"pages": written, "uncropped": warnings, "errors": errors, "file": str(target)}


def cli_main(arguments: argparse.Namespace):
    folder = Path(arguments.carpeta).expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"No existe la carpeta: {folder}")
    try:
        paths = discover_images(folder)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    destination = Path(arguments.salida).expanduser().resolve()
    print(f"Imágenes encontradas: {len(paths)}")
    result = create_pdf(paths, destination, auto_crop=not arguments.sin_recorte,
                        progress=lambda n, total, name: print(f"[{n}/{total}] {name}"))
    print(f"PDF listo: {result['file']} ({result['pages']} páginas)")
    if result["uncropped"]:
        print(f"Aviso: {len(result['uncropped'])} fotos sin recorte seguro, se incluyeron completas.")
    if result["errors"]:
        print("Archivos que fallaron:")
        print("\n".join(result["errors"]))


def gui_main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class DigitalizadorApp:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.root.title("Digitalizador de fotos")
            self.root.geometry("1050x720")
            self.root.minsize(780, 570)
            self.folder: Path | None = None
            self.paths: list[Path] = []
            self.manual_corners: dict[Path, np.ndarray] = {}
            self.pdf_name = tk.StringVar(value="")
            self.previous_folder_name: str | None = None
            self.auto_crop = tk.BooleanVar(value=True)
            self.info = tk.StringVar(value="Selecciona una carpeta con las fotos de tus documentos.")
            self.progress_text = tk.StringVar(value="")
            self.events: queue.Queue = queue.Queue()
            self.busy = False
            self.preview_photos: list[ImageTk.PhotoImage] = []

            style = ttk.Style(root)
            if "clam" in style.theme_names():
                style.theme_use("clam")
            style.configure("Main.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 10))
            style.configure("Small.TButton", font=("Segoe UI", 10), padding=(12, 7))
            style.configure("TLabel", font=("Segoe UI", 10))
            style.configure("TCheckbutton", font=("Segoe UI", 10))
            style.configure("TProgressbar", thickness=14)
            root.configure(bg="#F6F7F8")

            body = ttk.Frame(root, padding=20)
            body.pack(fill="both", expand=True)
            ttk.Label(body, text="Fotografías a PDF", font=("Segoe UI", 21, "bold")).pack(anchor="w")
            ttk.Label(body, text="Conserva el color original. Sin OCR ni conversión de texto.").pack(anchor="w", pady=(4, 16))

            actions = ttk.Frame(body)
            actions.pack(fill="x")
            self.folder_button = ttk.Button(actions, text="1. Elegir carpeta de fotos", style="Main.TButton", command=self.pick_folder)
            self.folder_button.pack(side="left")
            self.make_button = ttk.Button(actions, text="3. Crear PDF", style="Main.TButton", command=self.make_pdf)
            self.make_button.pack(side="right")
            self.make_button.state(["disabled"])
            name_row = ttk.Frame(body)
            name_row.pack(fill="x", pady=(12, 2))
            ttk.Label(name_row, text="2. Nombre del PDF:", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
            self.name_entry = ttk.Entry(name_row, textvariable=self.pdf_name, font=("Segoe UI", 11), width=44)
            self.name_entry.pack(side="left", fill="x", expand=True)
            ttk.Label(name_row, text=".pdf", font=("Segoe UI", 10)).pack(side="left", padx=(5, 0))
            ttk.Label(body, textvariable=self.info, wraplength=920).pack(anchor="w", pady=(6, 9))
            crop_row = ttk.Frame(body)
            crop_row.pack(fill="x", pady=(0, 4))
            ttk.Checkbutton(crop_row, text="Recortar y enderezar las hojas automáticamente", variable=self.auto_crop,
                            command=self.refresh_preview).pack(side="left")
            self.manual_button = ttk.Button(crop_row, text="Ajustar esquinas de esta hoja", style="Small.TButton", command=self.adjust_corners)
            self.manual_button.pack(side="right")
            self.manual_button.state(["disabled"])
            ttk.Label(body, text="El programa elimina el fondo cuando identifica la hoja. Puedes ajustar sus cuatro esquinas si es necesario.",
                      foreground="#667085").pack(anchor="w", pady=(0, 10))

            panes = ttk.Panedwindow(body, orient="horizontal")
            panes.pack(fill="both", expand=True)
            left = ttk.Frame(panes, width=230)
            right = ttk.Frame(panes)
            panes.add(left, weight=1)
            panes.add(right, weight=4)
            ttk.Label(left, text="Páginas (orden de captura)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
            listcontainer = ttk.Frame(left)
            listcontainer.pack(fill="both", expand=True)
            self.listbox = tk.Listbox(listcontainer, activestyle="none", exportselection=False,
                                      font=("Segoe UI", 10), selectmode="browse", borderwidth=0)
            scroll = ttk.Scrollbar(listcontainer, orient="vertical", command=self.listbox.yview)
            self.listbox.configure(yscrollcommand=scroll.set)
            self.listbox.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            self.listbox.bind("<<ListboxSelect>>", lambda _event: self.refresh_preview())

            ttk.Label(right, text="Vista previa", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=(16, 0), pady=(0, 6))
            previews = ttk.Frame(right)
            previews.pack(fill="both", expand=True, padx=(16, 0))
            self.preview_orig = tk.Label(previews, text="Original", bg="#E9EDF0", compound="top", font=("Segoe UI", 10))
            self.preview_result = tk.Label(previews, text="Procesado", bg="#E9EDF0", compound="top", font=("Segoe UI", 10))
            self.preview_orig.pack(side="left", fill="both", expand=True, padx=(0, 5))
            self.preview_result.pack(side="left", fill="both", expand=True, padx=(5, 0))
            self.preview_status = tk.StringVar(value="")
            ttk.Label(right, textvariable=self.preview_status, wraplength=640).pack(anchor="w", padx=(16, 0), pady=(7, 0))

            footer = ttk.Frame(body)
            footer.pack(fill="x", pady=(14, 0))
            self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
            self.progress.pack(fill="x")
            ttk.Label(footer, textvariable=self.progress_text).pack(anchor="w", pady=(6, 0))
            root.after(100, self.poll_events)

        def pick_folder(self):
            folder = filedialog.askdirectory(title="Selecciona la carpeta con fotografías")
            if not folder:
                return
            chosen_folder = Path(folder)
            try:
                chosen_paths = discover_images(chosen_folder)
            except ValueError as exc:
                messagebox.showerror("Metadatos de captura", str(exc))
                return
            self.folder = chosen_folder
            self.paths = chosen_paths
            self.manual_corners = {}
            if not self.pdf_name.get().strip() or self.pdf_name.get().strip() == self.previous_folder_name:
                self.pdf_name.set(self.folder.name)
            self.previous_folder_name = self.folder.name
            self.listbox.delete(0, "end")
            for photo in self.paths:
                captured = capture_datetime(photo)
                self.listbox.insert("end", f"{captured:%d/%m %H:%M:%S}  {photo.name}")
            self.info.set(
                f"{len(self.paths)} fotografías ordenadas por fecha/hora original de captura (EXIF). "
                "No por nombre, descarga o subida a OneDrive."
            )
            self.make_button.state(["!disabled"] if self.paths else ["disabled"])
            self.manual_button.state(["!disabled"] if self.paths else ["disabled"])
            if self.paths:
                self.listbox.selection_set(0)
                self.refresh_preview()
            else:
                self.set_preview(self.preview_orig, None, "Original")
                self.set_preview(self.preview_result, None, "Procesado")
                messagebox.showinfo("No hay fotografías", "Esta carpeta no contiene fotos JPG, PNG o HEIC compatibles.")

        def thumb(self, image: Image.Image) -> ImageTk.PhotoImage:
            # El aspecto se mantiene, sin modificar el archivo de origen.
            copy = image.copy()
            copy.thumbnail((340, 410), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(copy)

        def set_preview(self, widget: tk.Label, image: Image.Image | None, title: str):
            if image is None:
                widget.configure(image="", text=title)
                return
            ph = self.thumb(image)
            self.preview_photos.append(ph)
            widget.configure(image=ph, text=title, padx=5, pady=5)

        def refresh_preview(self):
            if self.busy or not self.paths:
                return
            selected = self.listbox.curselection()
            if not selected:
                return
            photo = self.paths[selected[0]]
            self.preview_photos.clear()
            try:
                original = open_color_image(photo)
                processed, cropped = prepare_page(photo, self.auto_crop.get(), self.manual_corners.get(photo))
                self.set_preview(self.preview_orig, original, "Original")
                self.set_preview(self.preview_result, processed, "Resultado PDF")
                original.close()
                processed.close()
                self.preview_status.set(
                    "Recorte ajustado manualmente." if cropped and self.auto_crop.get() and photo in self.manual_corners
                    else "Hoja detectada y enderezada." if cropped
                    else "No se detectó la hoja. Puedes ajustar sus esquinas manualmente."
                    if self.auto_crop.get() else "Sin recorte: imagen original completa."
                )
            except Exception as exc:
                self.set_preview(self.preview_orig, None, "Original")
                self.set_preview(self.preview_result, None, "Resultado")
                self.preview_status.set(f"No se pudo mostrar esta imagen: {exc}")

        def adjust_corners(self):
            """Editor opcional para las fotos difíciles, con cuatro puntos arrastrables."""
            if self.busy or not self.paths:
                return
            selected = self.listbox.curselection()
            if not selected:
                return
            photo = self.paths[selected[0]]
            try:
                original = open_color_image(photo)
            except Exception as exc:
                messagebox.showerror("No se puede abrir", str(exc))
                return
            w, h = original.size
            ratio = min(760 / w, 575 / h)
            width, height = round(w * ratio), round(h * ratio)
            preview = original.resize((width, height), Image.Resampling.LANCZOS)
            img = ImageTk.PhotoImage(preview)
            original_np = np.asarray(original)
            detected = find_document_corners(original_np)
            original.close()
            preview.close()
            initial = self.manual_corners.get(photo)
            if initial is None:
                initial = detected
            if initial is None:
                initial = np.float32([[w*.05, h*.05], [w*.95, h*.05],
                                     [w*.95, h*.95], [w*.05, h*.95]])
            points = (ordenar_esquinas(initial) * ratio).tolist()
            popup = tk.Toplevel(self.root)
            popup.title(f"Ajustar recorte: {photo.name}")
            popup.transient(self.root)
            popup.grab_set()
            container = ttk.Frame(popup, padding=14)
            container.pack(fill="both", expand=True)
            ttk.Label(container, text="Arrastra los cuatro círculos a las esquinas de la hoja.",
                      font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
            board = tk.Canvas(container, width=width, height=height, highlightthickness=0,
                              borderwidth=0, cursor="crosshair", bg="#1B242C")
            board.pack()
            board.create_image(0, 0, image=img, anchor="nw")
            board.image_reference = img
            poly = board.create_polygon(0, 0, 0, 0, outline="#16A6DB", fill="", width=3)
            handles = [board.create_oval(0, 0, 0, 0, fill="#16A6DB", outline="white", width=2)
                       for _ in range(4)]
            labels = [board.create_text(0, 0, fill="white", text=str(i+1), font=("Segoe UI", 10, "bold"))
                      for i in range(4)]
            selected_handle = [None]

            def redraw():
                board.coords(poly, *[value for xy in points for value in xy])
                for i, (x, y) in enumerate(points):
                    board.coords(handles[i], x-11, y-11, x+11, y+11)
                    board.coords(labels[i], x, y)

            def near_handle(event):
                distances = [np.hypot(x-event.x, y-event.y) for x, y in points]
                closest = int(np.argmin(distances))
                return closest if distances[closest] < 38 else None

            def press(event):
                selected_handle[0] = near_handle(event)

            def drag(event):
                i = selected_handle[0]
                if i is not None:
                    points[i] = [max(0, min(width-1, event.x)), max(0, min(height-1, event.y))]
                    redraw()

            board.bind("<ButtonPress-1>", press)
            board.bind("<B1-Motion>", drag)
            board.bind("<ButtonRelease-1>", lambda _event: selected_handle.__setitem__(0, None))

            def reset():
                quad = detected if detected is not None else np.float32([
                    [w*.05, h*.05], [w*.95, h*.05], [w*.95, h*.95], [w*.05, h*.95]])
                points[:] = (ordenar_esquinas(quad) * ratio).tolist()
                redraw()

            def save():
                quad = np.asarray(points, dtype=np.float32) / ratio
                # Comprobar que no se cruzan las aristas ni se recorta una zona diminuta.
                shape = quad.reshape(-1, 1, 2)
                if not cv2.isContourConvex(shape) or cv2.contourArea(shape) < .07*w*h:
                    messagebox.showwarning("Esquinas incorrectas", "Los puntos deben formar una hoja sin cruzarse.", parent=popup)
                    return
                self.manual_corners[photo] = quad
                self.auto_crop.set(True)
                popup.destroy()
                self.refresh_preview()

            redraw()
            controls = ttk.Frame(container)
            controls.pack(fill="x", pady=(11, 0))
            ttk.Button(controls, text="Volver a detección automática", command=reset).pack(side="left")
            ttk.Button(controls, text="Cancelar", command=popup.destroy).pack(side="right", padx=(7, 0))
            ttk.Button(controls, text="Guardar recorte", command=save).pack(side="right")

        @staticmethod
        def clean_name(value: str) -> str:
            name = value.strip()
            if name.lower().endswith(".pdf"):
                name = name[:-4].strip()
            if not name or name in {".", ".."}:
                raise ValueError("Escribe un nombre para el PDF.")
            if any(char in name for char in '<>:"/\\|?*') or name.endswith("."):
                raise ValueError("El nombre contiene caracteres que Windows no permite.")
            if name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
                raise ValueError("Elige otro nombre, Windows reserva ese nombre.")
            return name + ".pdf"

        def make_pdf(self):
            if not self.folder or not self.paths or self.busy:
                return
            try:
                target_name = self.clean_name(self.pdf_name.get())
            except ValueError as exc:
                messagebox.showwarning("Nombre del PDF", str(exc))
                self.name_entry.focus_set()
                return
            dest = filedialog.asksaveasfilename(
                title="Guardar documento PDF", initialfile=target_name,
                defaultextension=".pdf", filetypes=[("Documento PDF", "*.pdf")],
                initialdir=str(self.folder.parent),
            )
            if not dest:
                return
            self.busy = True
            self.folder_button.state(["disabled"])
            self.make_button.state(["disabled"])
            self.manual_button.state(["disabled"])
            self.name_entry.state(["disabled"])
            self.progress.configure(maximum=len(self.paths), value=0)
            self.progress_text.set(f"Preparando {len(self.paths)} páginas...")
            paths = list(self.paths)
            should_crop = self.auto_crop.get()
            manual = dict(self.manual_corners)

            def worker():
                try:
                    output = create_pdf(paths, Path(dest), should_crop,
                        progress=lambda number, total, name: self.events.put(("progress", number, total, name)),
                        manual_corners=manual)
                    self.events.put(("done", output))
                except Exception as exc:
                    self.events.put(("failed", str(exc), traceback.format_exc()))
            threading.Thread(target=worker, daemon=True).start()

        def poll_events(self):
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                if event[0] == "progress":
                    _, n, total, name = event
                    self.progress.configure(value=n)
                    self.progress_text.set(f"Procesando {n} de {total}: {name}")
                elif event[0] == "done":
                    info = event[1]
                    self.reset_controls()
                    details = f"PDF creado con {info['pages']} páginas.\n\n{info['file']}"
                    if info["uncropped"]:
                        details += f"\n\n{len(info['uncropped'])} fotos no se pudieron recortar con seguridad y se incluyeron completas.\n" + "\n".join(info["uncropped"][:8])
                    if info["errors"]:
                        details += f"\n\n{len(info['errors'])} fotos no se pudieron incluir:\n" + "\n".join(info["errors"][:8])
                    self.progress_text.set(f"Listo: {info['pages']} páginas guardadas.")
                    messagebox.showinfo("PDF terminado", details)
                elif event[0] == "failed":
                    self.reset_controls()
                    self.progress_text.set("No se pudo crear el PDF.")
                    messagebox.showerror("Error al generar PDF", event[1])
            self.root.after(100, self.poll_events)

        def reset_controls(self):
            self.busy = False
            self.folder_button.state(["!disabled"])
            self.make_button.state(["!disabled"] if self.paths else ["disabled"])
            self.manual_button.state(["!disabled"] if self.paths else ["disabled"])
            self.name_entry.state(["!disabled"])

    root = tk.Tk()
    DigitalizadorApp(root)
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Digitaliza fotografías a PDF, con color original y sin OCR.")
    parser.add_argument("--carpeta", help="Carpeta de fotografías, opcional para usar sin interfaz.")
    parser.add_argument("--salida", help="Archivo PDF de salida al usar --carpeta.")
    parser.add_argument("--sin-recorte", action="store_true", help="No intentar recortar ni enderezar las hojas.")
    args = parser.parse_args()
    if args.carpeta or args.salida:
        if not args.carpeta or not args.salida:
            parser.error("Para el modo automático debes indicar --carpeta y --salida.")
        cli_main(args)
    else:
        gui_main()
