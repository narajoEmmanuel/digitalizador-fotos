# Digitalizador de Fotos

Una aplicación local para **Windows** que convierte fotografías de documentos en un PDF multipágina, conservando **los colores originales**. Detecta los bordes del papel, intenta recortarlo y enderezarlo y permite ajustar manualmente las cuatro esquinas si hace falta. **No utiliza OCR ni transcribe texto**.

## Funciones

- Selección de una carpeta de imágenes, en orden natural (`foto1`, `foto2`, `foto10`).
- Detección y corrección de perspectiva de cada hoja.
- Comparación entre foto original y página procesada.
- Corrección manual opcional con cuatro esquinas ajustables.
- Campo para **elegir el nombre del PDF** antes de guardarlo.
- Exportación a PDF con páginas ajustadas a los recortes, sin márgenes añadidos.
- Conservación de las fotografías originales. Todo se procesa localmente.

## Requisitos

- Windows 10 u 11.
- Python 3.10 o superior, instalado con la opción de añadirlo al PATH.
- Conexión a Internet **solo para instalar dependencias la primera vez**.

## Inicio rápido

1. Descarga el código ZIP del repositorio y descomprímelo.
2. Abre `INICIAR.bat` con doble clic. Preparará un entorno `.venv` e instalará las dependencias.
3. Selecciona una carpeta con fotografías de las hojas.
4. Escribe el nombre del documento PDF.
5. Revisa algunas páginas. Corrige manualmente las esquinas si el recorte no es preciso.
6. Pulsa **Crear PDF** y elige dónde guardarlo.

Formatos de entrada: JPG, JPEG, PNG, HEIC, HEIF, WebP, TIFF y BMP.

## Consejos para mejores recortes

- Fotografía las hojas **sobre una superficie de color diferente al papel**.
- Mantén las cuatro esquinas completamente visibles.
- Coloca el teléfono lo más perpendicular posible y evita sombras duras.
- Usa una carpeta por documento, con fotos en el orden correcto.
- Si el recorte automático no es seguro, la aplicación conservará **la foto completa**, para evitar pérdida de contenido.

## Uso por consola (opcional)

```powershell
.\.venv\Scripts\python.exe digitalizador.py --carpeta "C:\Fotos" --salida "C:\Documentos\Mi documento.pdf"
```

Para incluir las fotografías enteras, sin recortes:

```powershell
.\.venv\Scripts\python.exe digitalizador.py --carpeta "C:\Fotos" --salida "C:\Documentos\Mi documento.pdf" --sin-recorte
```

## Pruebas

Con dependencias instaladas:

```powershell
python -m unittest discover -s tests -v
```

## Privacidad y limitaciones

- No hay conexión con servidores ni subida de imágenes. No incluye analítica.
- No se editan, sustituyen ni eliminan las fotos originales.
- La detección depende del contraste, la iluminación y que el documento sea visible. Comprueba el resultado antes de archivar o descartar el papel.
- Los ajustes manuales de las cuatro esquinas solo se mantienen en la sesión actual.
- Los resultados se guardan como imágenes JPEG de alta calidad dentro del PDF, por lo que no son píxeles idénticos a la foto original. Se mantiene la apariencia a color, sin filtros de blanco y negro.
- Si una fotografía no puede abrirse, se informa del error y se genera el PDF con las páginas válidas. Revisa el resumen al finalizar.

## Archivos principales

- `digitalizador.py`: interfaz, importación de fotografías y generación del PDF.
- `recorte.py`: detector de hojas y esquinas.
- `INICIAR.bat`: inicio sencillo en Windows.
- `requirements.txt`: dependencias.
- `LEEME.txt`: instrucciones incluidas desde la versión 1.1.
- `tests/`: pruebas automatizadas.

**Versión**: 1.1, basada en la versión funcional probada con fotografías de ejemplo. 
