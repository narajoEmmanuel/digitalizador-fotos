# Historial de cambios

## 1.2 (2026-11-01)

- Orden de páginas basado en `EXIF DateTimeOriginal` de las fotos, independiente del nombre y las fechas de OneDrive o Windows.
- Soporte de subsegundos y offset horario EXIF cuando estén disponibles.
- La aplicación se detiene y señala las fotos sin fecha de captura para evitar un orden inventado.
- La interfaz muestra la fecha y hora de toma de cada página.
- Nuevas pruebas automáticas de orden cronológico y metadatos ausentes.

## 1.1 (2026-11-01)

- Recorte mejorado mediante detección de bordes, luminosidad y color del fondo.
- Ajuste manual de las cuatro esquinas cuando el recorte automático falla.
- Nombre personalizado para el PDF antes de crearlo.
- Páginas del PDF sin márgenes artificiales.
- Se mantienen los colores originales y no se realiza OCR ni transcripción.

## 1.0 (2026-11-01)

- Procesamiento local por lotes de fotografías.
- Orden natural de las imágenes y creación de un PDF multipágina.
- Interfaz de Windows y un iniciador por doble clic.
