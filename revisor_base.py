"""Componentes gráficos compartidos del revisor previo a exportar el PDF."""
from concurrent.futures import ThreadPoolExecutor
import queue
import numpy as np
import cv2
from PIL import Image, ImageTk
from recorte import detectar_hoja, ordenar_esquinas


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
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.events = queue.Queue()
        self.generation = self.selection_token = 0
        self.start = 0
        self.photos, self.buttons, self.thumb_versions = {}, {}, {}
        self.selected = None
        self.saved_indices = set()
        self.closed = False
        self.editor_image = self.editor_photo = None
        self.points = self.detected_points = self.full_size = None
        self.drag_index = self.image_bounds = None
        self.resize_after = None
        self.thumb_size = (max(85,min(180,self.window.winfo_screenwidth()//10)),
                           max(78,min(155,self.window.winfo_screenheight()//6)))
        body = ttk.Frame(self.window, padding=12)
        body.pack(fill='both', expand=True)
        top = ttk.Frame(body)
        top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, text="Revisa todas las hojas antes de exportar", font=('Segoe UI', 15, 'bold')).pack(side='left')
        ttk.Button(top, text='Cerrar revisión', command=self.close).pack(side='right')
        self.panes = ttk.Panedwindow(body, orient='horizontal')
        self.panes.pack(fill='both', expand=True)
        left, right = ttk.Frame(self.panes), ttk.Frame(self.panes)
        self.panes.add(left, weight=4)
        self.panes.add(right, weight=6)
        self.window.after(160, self._split)
        nav = ttk.Frame(left)
        nav.pack(fill='x', pady=(0, 6))
        ttk.Button(nav, text='◀ 16 anteriores', command=lambda: self.show(self.start-16)).pack(side='left')
        self.label = tk.StringVar()
        ttk.Label(nav, textvariable=self.label).pack(side='left', padx=8)
        ttk.Button(nav, text='16 siguientes ▶', command=lambda: self.show(self.start+16)).pack(side='right')
        self.grid = ttk.Frame(left)
        self.grid.pack(fill='both', expand=True)
        bar = ttk.Frame(right)
        bar.pack(fill='x', pady=(0, 6))
        self.current_label = tk.StringVar(value='Selecciona una página a la izquierda')
        ttk.Label(bar, textvariable=self.current_label).pack(side='left')
        self.save_button = ttk.Button(bar, text='Guardar recorte', command=self.save)
        self.save_button.pack(side='right', padx=5)
        self.reset_button = ttk.Button(bar, text='Detección automática', command=self.reset)
        self.reset_button.pack(side='right')
        self.save_button.state(['disabled'])
        self.reset_button.state(['disabled'])
        self.board = tk.Canvas(right, bg='#242A30', highlightthickness=0, cursor='crosshair')
        self.board.pack(fill='both', expand=True)
        self.board.bind('<Configure>', self._resize)
        self.board.bind('<ButtonPress-1>', self._press)
        self.board.bind('<B1-Motion>', self._drag)
        self.board.bind('<ButtonRelease-1>', lambda _event: setattr(self,'drag_index',None))
        self.status = tk.StringVar(value='Selecciona una hoja, arrastra cuatro puntos y guarda.')
        ttk.Label(right, textvariable=self.status, wraplength=610).pack(fill='x', pady=(7, 0))
        self.show(0)
        self.window.after(80, self.poll)

    def _split(self):
        if not self.closed:
            self.panes.sashpos(0, int(self.panes.winfo_width()*.42))

    def show(self, start):
        self.start = max(0, min(start, max(0,(len(self.paths)-1)//16*16)))
        self.generation += 1
        gen = self.generation
        for child in self.grid.winfo_children():
            child.destroy()
        self.buttons.clear()
        self.photos.clear()
        batch = list(enumerate(self.paths[self.start:self.start+16], self.start))
        self.label.set(f'{self.start+1} a {self.start+len(batch)} de {len(self.paths)}')
        for offset, (index, path) in enumerate(batch):
            r,c = divmod(offset,4)
            cell = self.ttk.Frame(self.grid)
            cell.grid(row=r, column=c, sticky='nsew', padx=2, pady=2)
            button = self.tk.Button(cell, text='Cargando...', compound='top', bg='#E9EEF1',
                     relief='flat', command=lambda i=index: self.choose(i))
            button.pack(fill='both',expand=True)
            caption = self.ttk.Label(cell,text=self._page_caption(index),anchor='center')
            caption.pack(fill='x')
            self.buttons[index] = (button,caption)
            self.thumb_versions[index] = self.thumb_versions.get(index,0)+1
        for i in range(4):
            self.grid.columnconfigure(i, weight=1, uniform='photos')
            self.grid.rowconfigure(i, weight=1, uniform='photos')
        def worker():
            for i,path in batch:
                if self.closed or gen != self.generation:
                    return
                self._thumb(gen,i,path,self.thumb_versions[i])
        self.pool.submit(worker)
        self._highlight_selection()

    def _page_caption(self,index):
        return f'Página {index+1}' + (' ✓' if index in self.saved_indices else '')

    def _thumb(self, gen, index, path, version):
        try:
            im = self.preview_provider(path)
            im.thumbnail(self.thumb_size,Image.Resampling.BILINEAR)
            self.events.put(('thumb',gen,index,version,im,None))
        except Exception as e:
            self.events.put(('thumb',gen,index,version,None,str(e)))

    def refresh_item(self,index):
        if self.closed or index not in self.buttons:
            return
        self.thumb_versions[index] = self.thumb_versions.get(index,0)+1
        self.pool.submit(self._thumb,self.generation,index,self.paths[index],self.thumb_versions[index])

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
                _,gen,index,version,im,error = event
                if gen!=self.generation or index not in self.buttons or version!=self.thumb_versions.get(index):
                    if im is not None:
                        im.close()
                    continue
                button,_ = self.buttons[index]
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
                detected=detectar_hoja(np.asarray(img))
                self.events.put(('editor',token,index,img,size,detected,None))
            except Exception as exc:
                self.events.put(('editor',token,index,None,None,None,str(exc)))
        self.pool.submit(worker)

    def _load_editor(self,preview,size,detected):
        if self.editor_image is not None:
            self.editor_image.close()
        self.editor_image=preview
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
        if self.editor_image is not None:
            self.editor_image.close()
        self.window.destroy()
