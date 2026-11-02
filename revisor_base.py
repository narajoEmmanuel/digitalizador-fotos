"""Componentes gráficos compartidos del revisor previo a exportar el PDF."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from threading import Lock
import queue
import numpy as np
import cv2
from PIL import Image, ImageTk
from recorte import detectar_hoja, ordenar_esquinas


def matrix_thumbnail_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Limita las miniaturas para que los controles inferiores sigan visibles."""
    left_width = max(245, int(screen_width * .36) - 20)
    width = max(48, min(160, (left_width - 28) // 4))
    # Cuatro filas más su número de página, navegación y botones inferiores.
    height = max(48, min(160, (screen_height - 360) // 4 - 17))
    return width, height


def validated_photo_corners(points, full_size):
    w, h = full_size
    corners = np.asarray(points, dtype=np.float32).reshape(4, 2)
    if (not np.isfinite(corners).all() or
        (corners[:, 0] < 0).any() or (corners[:, 0] > w-1).any() or
        (corners[:, 1] < 0).any() or (corners[:, 1] > h-1).any() or
        not cv2.isContourConvex(corners.reshape(-1, 1, 2)) or
        cv2.contourArea(corners) < .07*w*h):
        raise ValueError("Coloca los cuatro puntos alrededor de la hoja, sin cruzarlos.")
    return corners


class PhotoMatrix:
    PAGE_SIZE = 16

    def __init__(self, parent, paths, preview_provider, on_save, photo_loader, manual_corners):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.paths = list(paths)
        self.preview_provider, self.on_save = preview_provider, on_save
        self.photo_loader, self.manual_corners = photo_loader, manual_corners
        self.window = tk.Toplevel(parent)
        self.window.title("Revisión de hojas antes del PDF")
        self.window.geometry("1260x810")
        self.window.minsize(790, 510)
        if self.window.tk.call('tk', 'windowingsystem') == 'win32':
            self.window.state('zoomed')
        else:
            try:
                self.window.attributes('-zoomed', True)
            except tk.TclError:
                pass
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.thumb_pool = ThreadPoolExecutor(max_workers=2)
        self.quick_pool = ThreadPoolExecutor(max_workers=2)
        self.quick_lock = Lock()
        self.quick_cache = OrderedDict()
        self.events = queue.Queue()
        self.generation = self.selection_token = 0
        self.start = 0
        self.photos, self.buttons, self.thumb_versions = {}, {}, {}
        self.crop_warnings = {}
        self.selected = None
        self.editor_loaded_index = None
        self.saved_indices = set()
        self.closed = False
        self.editor_image = self.editor_photo = None
        self.points = self.detected_points = self.full_size = None
        self.drag_index = self.image_bounds = None
        self.resize_after = None
        self.thumb_size = matrix_thumbnail_size(
            self.window.winfo_screenwidth(), self.window.winfo_screenheight())
        body = ttk.Frame(self.window, padding=8)
        body.pack(fill='both', expand=True)
        self.panes = ttk.Panedwindow(body, orient='horizontal')
        self.panes.pack(fill='both', expand=True)
        left, right = ttk.Frame(self.panes), ttk.Frame(self.panes)
        self.left_panel, self.right_panel = left, right
        self.panes.add(left, weight=4)
        self.panes.add(right, weight=7)
        self.window.after(160, self._split)

        # El panel izquierdo contiene la matriz y todos los controles.
        top = ttk.Frame(left)
        top.pack(fill='x', pady=(0, 5))
        ttk.Label(top, text="Revisión", font=('Segoe UI', 13, 'bold')).pack(side='left')
        ttk.Button(top, text='Cerrar', command=self.close).pack(side='right')
        nav = ttk.Frame(left)
        nav.pack(fill='x', pady=(0, 5))
        ttk.Button(nav, text='◀', command=lambda: self.show(self.start-16)).pack(side='left')
        self.label = tk.StringVar()
        ttk.Label(nav, textvariable=self.label).pack(side='left', padx=8)
        ttk.Button(nav, text='▶', command=lambda: self.show(self.start+16)).pack(side='right')
        self.grid = ttk.Frame(left)

        # Reservar primero espacio fijo para los controles inferiores.
        # Si se empaqueta la matriz antes, sus 16 miniaturas desplazan los
        # botones fuera de pantalla en monitores pequeños o con escalado.
        self.controls = ttk.Frame(left)
        self.controls.pack(side='bottom', fill='x', pady=(5, 0))
        page_bar = ttk.Frame(self.controls)
        page_bar.pack(fill='x')
        self.current_label = tk.StringVar(value='Selecciona una página')
        ttk.Label(page_bar, textvariable=self.current_label).pack(side='left')
        self.action_bar = ttk.Frame(self.controls)
        self.action_bar.pack(fill='x', pady=(3, 0))
        self.save_button = ttk.Button(self.action_bar, text='Guardar recorte', command=self.save)
        self.save_button.pack(side='right', padx=5)
        self.reset_button = ttk.Button(self.action_bar, text='Detección automática', command=self.reset)
        self.reset_button.pack(side='right')
        self.save_button.state(['disabled'])
        self.reset_button.state(['disabled'])
        self.status = tk.StringVar(value='')
        self.status_widget = ttk.Label(self.controls, textvariable=self.status, wraplength=260)
        self.status_widget.pack(fill='x', pady=(4, 0))
        # La matriz usa únicamente el espacio que sobra, nunca tapa controles.
        self.grid.pack(side='top', fill='both', expand=True)

        # La derecha se reserva íntegramente para la imagen o sus esquinas.
        self.board = tk.Canvas(right, bg='#242A30', highlightthickness=0, cursor='crosshair')
        self.board.pack(fill='both', expand=True)
        self.board.bind('<Configure>', self._resize)
        self.board.bind('<ButtonPress-1>', self._press)
        self.board.bind('<B1-Motion>', self._drag)
        self.board.bind('<ButtonRelease-1>', lambda _event: setattr(self,'drag_index',None))
        self.show(0)
        self.window.after(80, self.poll)

    def _split(self):
        if not self.closed:
            self.panes.sashpos(0, int(self.panes.winfo_width()*.36))

    def show(self, start):
        self.start = max(0, min(start, max(0,(len(self.paths)-1)//16*16)))
        self.generation += 1
        gen = self.generation
        for child in self.grid.winfo_children():
            child.destroy()
        self.buttons.clear()
        self.photos.clear()
        batch = list(enumerate(self.paths[self.start:self.start+16], self.start))
        self.label.set(f'{self.start+1} a {self.start+len(batch)} / {len(self.paths)}')
        for offset, (index, path) in enumerate(batch):
            r,c = divmod(offset,4)
            cell = self.ttk.Frame(self.grid)
            cell.grid(row=r, column=c, sticky='nsew', padx=2, pady=2)
            button = self.tk.Button(cell, text='…', compound='top', bg='#E9EEF1',
                     relief='flat', command=lambda i=index: self.choose(i))
            button.pack(fill='both',expand=True)
            caption = self.ttk.Label(cell,text=self._page_caption(index),anchor='center')
            caption.pack(fill='x')
            self.buttons[index] = (button,caption)
            self.thumb_versions[index] = self.thumb_versions.get(index,0)+1
        for i in range(4):
            self.grid.columnconfigure(i, weight=1, uniform='photos')
            self.grid.rowconfigure(i, weight=1, uniform='photos')
        for i, path in batch:
            self.thumb_pool.submit(self._thumb, gen, i, path, self.thumb_versions[i])
        self._highlight_selection()

    def _page_caption(self,index):
        return f'Página {index+1}' + (' ✓' if index in self.saved_indices else '')

    def get_quick_preview(self, path):
        """Imagen procesada ligera compartida por miniaturas y vista de lectura."""
        with self.quick_lock:
            item = self.quick_cache.get(path)
            if item is not None:
                self.quick_cache.move_to_end(path)
                im, warning = item
                return im.copy(), warning
        result = self.preview_provider(path)
        im, warning = result if isinstance(result, tuple) else (result, None)
        with self.quick_lock:
            if self.closed:
                im.close()
                raise RuntimeError("Se cerró el revisor.")
            old = self.quick_cache.pop(path, None)
            if old is not None:
                old[0].close()
            self.quick_cache[path] = (im, warning)
            while len(self.quick_cache) > 24:
                _, expired = self.quick_cache.popitem(last=False)
                expired[0].close()
            return im.copy(), warning

    def discard_quick_preview(self, path):
        with self.quick_lock:
            old = self.quick_cache.pop(path, None)
            if old:
                old[0].close()

    def _thumb(self, gen, index, path, version):
        if self.closed or gen != self.generation:
            return
        try:
            im, warning = self.get_quick_preview(path)
            im.thumbnail(self.thumb_size, Image.Resampling.BILINEAR)
            self.events.put(('thumb',gen,index,version,im,None,warning))
        except Exception as e:
            self.events.put(('thumb',gen,index,version,None,str(e),"No se pudo cargar"))

    def refresh_item(self,index):
        if self.closed or index not in self.buttons:
            return
        self.discard_quick_preview(self.paths[index])
        self.thumb_versions[index] = self.thumb_versions.get(index,0)+1
        self.thumb_pool.submit(self._thumb,self.generation,index,self.paths[index],self.thumb_versions[index])

    def _highlight_selection(self):
        for i,(button,caption) in self.buttons.items():
            button.configure(bg='#D1EBFA' if i == self.selected else '#E9EEF1')
            caption.configure(text=self._page_caption(i))

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0]=='thumb':
                _,gen,index,version,im,error,warning = event
                if gen!=self.generation or index not in self.buttons or version!=self.thumb_versions.get(index):
                    if im is not None:
                        im.close()
                    continue
                button,caption = self.buttons[index]
                if warning:
                    self.crop_warnings[self.paths[index]] = warning
                else:
                    self.crop_warnings.pop(self.paths[index], None)
                caption.configure(text=self._page_caption(index),
                                  foreground="#B54708" if warning else "#344054")
                if im is None:
                    button.configure(text='Error de imagen')
                else:
                    picture = ImageTk.PhotoImage(im)
                    im.close()
                    self.photos[index] = picture
                    button.configure(image=picture,text='')
            elif event[0]=='editor':
                _,token,index,preview,size,detected,error = event
                if token!=self.selection_token or index!=self.selected:
                    if preview is not None:
                        preview.close()
                    continue
                if error:
                    self.status.set(error)
                else:
                    self._load_editor(preview,size,detected)
        self.window.after(80,self.poll)

    def choose(self,index):
        if self.closed or not 0<=index<len(self.paths):
            return
        self.selected=index
        self.selection_token+=1
        token=self.selection_token
        self._highlight_selection()
        self.current_label.set(f'Página {index+1} de {len(self.paths)}')
        self.save_button.state(['disabled'])
        self.reset_button.state(['disabled'])
        self.board.delete('all')
        self.board.create_text(15,15,text='Preparando imagen...',fill='white',anchor='nw')
        def worker():
            try:
                img,size=self.photo_loader(self.paths[index],1600)
                from digitalizador import automatic_page_corners
                full, _problem = automatic_page_corners(self.paths[index])
                detected = (full * np.float32([img.width / size[0], img.height / size[1]])
                            if full is not None else None)
                self.events.put(('editor',token,index,img,size,detected,None))
            except Exception as exc:
                self.events.put(('editor',token,index,None,None,None,str(exc)))
        self.pool.submit(worker)

    def _load_editor(self,preview,size,detected):
        if self.editor_image is not None:
            self.editor_image.close()
        self.editor_image=preview
        self.editor_loaded_index = self.selected
        self.full_size=size
        w,h=size
        scale=np.float32([w/preview.width,h/preview.height])
        self.detected_points=ordenar_esquinas(detected)*scale if detected is not None else None
        saved=self.manual_corners.get(self.paths[self.selected])
        initial=saved if saved is not None else self.detected_points
        if initial is None:
            initial=np.float32([[w*.05,h*.05],[w*.95,h*.05],[w*.95,h*.95],[w*.05,h*.95]])
        self.points=np.array(initial,dtype=np.float32,copy=True)
        self.save_button.state(['!disabled'])
        self.reset_button.state(['!disabled'])
        self._draw_editor()

    def _resize(self,_event=None):
        if self.editor_image is None or self.closed:
            return
        if self.resize_after is not None:
            self.window.after_cancel(self.resize_after)
        self.resize_after=self.window.after(100,self._draw_editor)

    def _draw_editor(self):
        if self.closed or self.editor_image is None or self.points is None:
            return
        bw,bh=max(60,self.board.winfo_width()),max(60,self.board.winfo_height())
        iw,ih=self.editor_image.size
        scale=min((bw-46)/iw,(bh-46)/ih)
        dw,dh=max(1,int(iw*scale)),max(1,int(ih*scale))
        shown=self.editor_image.resize((dw,dh),Image.Resampling.BILINEAR)
        self.editor_photo=ImageTk.PhotoImage(shown)
        shown.close()
        x,y=(bw-dw)//2,(bh-dh)//2
        self.image_bounds=(x,y,dw,dh)
        self.board.delete('all')
        self.board.create_image(x,y,image=self.editor_photo,anchor='nw')
        self.polygon=self.board.create_polygon(0,0,0,0,outline='#16A6DB',fill='',width=3)
        self.handles=[self.board.create_oval(0,0,0,0,fill='#16A6DB',outline='white',width=2) for _ in range(4)]
        self._draw_corners()

    def _draw_corners(self):
        if self.points is None or self.image_bounds is None:
            return
        x,y,dw,dh=self.image_bounds
        w,h=self.full_size
        coords=[(x+float(px)/w*dw,y+float(py)/h*dh) for px,py in self.points]
        self.board.coords(self.polygon,*[v for pair in coords for v in pair])
        for i,(px,py) in enumerate(coords):
            self.board.coords(self.handles[i],px-10,py-10,px+10,py+10)

    def _press(self,event):
        if self.points is None or self.image_bounds is None:
            return
        x,y,dw,dh=self.image_bounds
        w,h=self.full_size
        distances=[np.hypot(x+float(px)/w*dw-event.x,y+float(py)/h*dh-event.y) for px,py in self.points]
        i=int(np.argmin(distances))
        self.drag_index=i if distances[i]<36 else None

    def _drag(self,event):
        if self.drag_index is None or self.points is None:
            return
        x,y,dw,dh=self.image_bounds
        w,h=self.full_size
        self.points[self.drag_index]=(max(0,min(w-1,(event.x-x)/dw*w)),
                                     max(0,min(h-1,(event.y-y)/dh*h)))
        self._draw_corners()

    def reset(self):
        if self.points is None:
            return
        w,h=self.full_size
        if self.detected_points is not None:
            self.points=self.detected_points.copy()
        else:
            self.points=np.float32([[w*.05,h*.05],[w*.95,h*.05],[w*.95,h*.95],[w*.05,h*.95]])
        self._draw_corners()

    def save(self):
        if self.selected is not None and self.points is not None:
            self.on_save(self.selected,validated_photo_corners(self.points,self.full_size))
            self.saved_indices.add(self.selected)
            self.refresh_item(self.selected)
            self._highlight_selection()

    def close(self):
        if self.closed:
            return
        self.closed=True
        self.generation+=1
        self.selection_token+=1
        if self.resize_after is not None:
            self.window.after_cancel(self.resize_after)
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.thumb_pool.shutdown(wait=False,cancel_futures=True)
        self.quick_pool.shutdown(wait=False,cancel_futures=True)
        with self.quick_lock:
            for image, _warning in self.quick_cache.values():
                image.close()
            self.quick_cache.clear()
        if self.editor_image is not None:
            self.editor_image.close()
        self.window.destroy()
