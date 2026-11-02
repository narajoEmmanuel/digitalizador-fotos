# Historial de cambios

## 1.6 (2026-11-01)

- Matriz maximizada con 16 miniaturas a la izquierda y editor continuo de esquinas a la derecha.
- Vista previa ampliada desde la imagen original, antes de crear el PDF, con zoom y desplazamiento.
- Sustituir e insertar imágenes en cualquier posición durante la revisión sin requerir EXIF de la foto nueva.
- El orden EXIF se conserva solo como orden inicial, los cambios manuales no se reordenan al exportar.
- Marcado de páginas aprobadas y advertencia al exportar con páginas pendientes.
- Pruebas para preservar el orden manual y proteger los originales.


## 1.5 (2026-11-01)

- Matriz rápida de 16 recortes previstos antes de crear el PDF, con navegación por bloques.
- Pulsar una miniatura selecciona la foto y abre su ajuste manual de cuatro esquinas.
- Vista final ampliada que renderiza el PDF guardado, con zoom, ajuste a ventana, desplazamiento y pantalla completa (F11).
- Visor ampliado accesible tanto desde la ventana principal como desde el editor de PDF existente.
- Renderizado en segundo plano y límite de memoria para las vistas, sin modificar ni recomprimir el archivo.
- Dos pruebas nuevas de integridad del PDF y zoom, además de comprobación visual de la interfaz.

## 1.4 (2026-11-01)

- Selección automática de hoja más fiable con fondos de color o estampados: contraste entre interior y exterior en cada lado del papel, sin preferir el marco de la imagen por su mayor tamaño.
- Ajuste manual dimensionado a la pantalla disponible, con los cuatro tiradores y los botones visibles en pantallas pequeñas.
- Margen visual alrededor de la fotografía para poder tomar los cuatro tiradores incluso junto al borde.
- Pruebas adicionales con papel perforado sobre fondo estampado y con marco de fotografía sin hoja.
- Se mantiene el procesamiento local, a color y sin OCR.

## 1.3 (2026-11-01)

- Editor de PDF existente: sustituir página, insertar antes/después y deshacer, sin necesitar fotos antiguas.
- Copia nueva de seguridad obligatoria: no se sobrescribe el PDF de origen.
- Contador y navegación rápida de páginas, campo «Ir a», teclas Alt+flechas y AvPág/RePág.
- Páginas ya digitalizadas se copian sin volver a convertirlas en JPG.
- Vistas previas ligeras, asíncronas, con caché y precarga de páginas adyacentes.
- Ajuste manual de esquinas carga en segundo hilo para evitar bloquear la ventana.
- Vista general del PDF con 16 miniaturas y salto directo a página, carga en segundo hilo.
- Aumentada la resolución máxima de exportación a 6000 píxeles y JPEG de calidad 97, sin OCR.
- Exportación inicial ahora aborta ante páginas fallidas en lugar de producir un archivo incompleto.
- 11 pruebas automatizadas para orden, recorte, protección de originales e inserción/reemplazo.

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
