# Decisiones tomadas de noche (para confirmar)

Estabas dormido, así que en cada pregunta abierta tomé el valor recomendado y lo apunto aquí. Si quieres cambiar alguna, dime la letra y el número (por ejemplo "G.4") y lo ajusto.

Fuentes: encargo `04-encargo-construccion.md` (Addendum), auditoría `01-auditoria-actual.md` §5 y fuentes `02-fuentes-tracklists.md` §5. Las secciones A a C responden a esas preguntas. Las demás recogen lo que se decidió al construir cada parte: D (motor), E (entradas y enriquecimiento), G (interfaz), M (marca) y N (unión final de todo).

## A. Preguntas de la auditoría (01 §5)

1. **Motor**: Sockseek 3.0.5, fijado por SHA-256, detrás de un único adaptador. Si da problemas, vuelta a sldl 2.6.0 autocontenido por el mismo adaptador (Ajustes > Motor). Siempre `--no-config` y todas las opciones explícitas.
   - Detalle: para sldl 2.6.0 no existe un zip win-x64. Se fija `sldl_win-x86_self-contained.zip`, que funciona en Windows de 64 bits sin instalar .NET.
2. **Licencia**: GPL-3.0-or-later (mutagen es GPL-2.0+ y el motor es GPL/AGPL). Van incluidos el LICENSE del motor, el enlace a su código fuente exacto y los avisos de terceros.
3. **Contador de compartidos**: modo honesto, como pedía el encargo. Los dos motores reciben `--no-modify-share-count`, así que ninguno anuncia en Soulseek una cifra de archivos compartidos. Sockseek 3.0.5 no enseña esa opción en su ayuda, pero su código sí la acepta (`Sockseek.Cli/Services/ConfigManager.cs:521-522`; el efecto está en `Sockseek.Core/Soulseek/SoulseekClientManager.cs:377-381`), así que ya no se pasa `--shared-files 0 --shared-folders 0`. Los tests de línea de comandos de los dos motores (`tests/engine/golden/`) exigen esa opción. En el primer uso aparece un aviso que recomienda compartir con Nicotine+ cuando no uses Tracklister, con otra cuenta si van a la vez.
4. **Duda solo por espectro** (posible FLAC falso): el archivo se queda en la carpeta del set, con su número y una marca en el informe. A `_dudosos\` solo van las dudas de identidad: otra canción, otra versión o una duración que no cuadra.
5. **"CDJ antiguos"**: un FLAC de más de 48 kHz o de más de 24 bits se convierte a AIFF de 48 kHz/24 bits, con aviso. Por debajo se conservan el sample rate y los bits. El FLAC original se guarda en `_originales\`. Nunca se escribe AIFF-C ni 32 bits float. Conversor: soundfile + mutagen (sin ffmpeg).
   - Añadido: 88,2 y 176,4 kHz bajan a 44,1 kHz en vez de a 48 kHz. Es una división exacta, así que suena mejor, y sigue dentro del límite de los CDJ.
   - Añadido: los WAV/AIFF de más de 48 kHz/24 bits, los AIFF-C y los WAV float también se convierten a AIFF PCM en este preset. El original se guarda en `_originales\`.
6. **MP3**: VBR V0 no se acepta. En la búsqueda se acepta un bitrate desconocido; después de descargar se exige un MP3 CBR de 320 kbps o más, leído en la cabecera. Si no cumple, queda como "no cumple formato" y se puede reintentar.
7. **"Reordenar carpeta existente"** (carpetas de la herramienta vieja): entra en la v1.0. Empareja artista y título de forma aproximada, con vista previa obligatoria y deshacer, y nunca sobrescribe.
8. **AcoustID**: v1.1, opcional y apagado por defecto. No está en la v1.0.
9. **GitHub**: repo `tracklister`. El usuario dueño es una constante (`GITHUB_OWNER` en `src/tracklister/config.py`) que rellenas al publicar.
10. **Windows**: solo Windows 10/11 de 64 bits.

## B. Preguntas de las fuentes (02 §5)

1. **Shazam**: v1.1. El Addendum lo saca de la v1.0.
2. **yt-dlp**: va aparte como `yt-dlp.exe`, con un botón "Actualizar yt-dlp" (`yt-dlp -U`) y su propia carpeta de caché (`%LOCALAPPDATA%\Tracklister\cache\yt-dlp`). Se incluye en el zip y en el primer uso se copia a `%LOCALAPPDATA%\Tracklister\tools\`, para que se pueda actualizar sin permisos de administrador.
3. **API key de YouTube**: no hace falta. **Cambio**: el campo opcional para la clave pasa a la v1.1. En la v1.0 yt-dlp cubre los comentarios sin clave.
4. **trackid.net**: importar el CSV (arrastrar y soltar), un botón "Abrir en trackid.net" y vigilar la carpeta Descargas. La vigilancia viene activada y se puede apagar en Ajustes. Solo recoge CSV nuevos con las columnas de trackid. Nunca se usan endpoints privados.
5. **Servicios de pago** (AudD/ACRCloud): no en la v1.0.
6. **Enriquecimiento** iTunes, luego Deezer, luego MusicBrainz: activado por defecto, con caché. Solo envía artista y título. MusicBrainz lleva un User-Agent con el nombre, la versión y la URL de la app, y va a 1 petición por segundo como mucho.
7. **Huecos de trackid de más de 90 s**: se convierten en filas "ID (hueco)", desmarcadas.
8. **Si dos fuentes discrepan**: trackid manda en los nombres; YouTube rellena huecos e IDs. La diferencia queda en "notas".
9. **Mixcloud**: la v1.0 solo genera el texto para copiar. La publicación por API va en la v1.1.
10. **Filas "revisar"**: desmarcadas, salvo que el enriquecimiento las confirme.

## C. Otros valores por defecto del encargo y de la construcción

1. **Lossless**: se pide FLAC/WAV/AIFF. Si una pista solo existe en MP3, se pregunta una vez por set, con una lista de casillas de esas pistas. Solo las marcadas se buscan en MP3 320.
2. **`.m4a`** queda fuera de Lossless, porque puede ser AAC.
3. **Filtros del motor** en todas las pasadas: `--strict-title`, `--strict-artist` (con el artista principal) y `--length-tol 3` si se conoce la duración. Sin `--strict-conditions` y sin `fast-search`. "Reintentar fallos" relaja `--strict-artist`.
4. **Verificación**:
   - puntuación de 80 o más = verificado;
   - de 50 a 79 = dudoso "revisar", que se queda en el set marcado;
   - menos de 50, o un fallo de identidad, versión o duración = `_dudosos\` con el motivo.
5. **Duración**: hasta ±3 s está bien; de 3 a 10 s, revisar; más de 10 s, duda de duración. Sin duración esperada no se comprueba y se anota "sin duración esperada".
6. **Nombres**: `NN - Artista - Titulo (Version).ext`, con el NN sacado del número de fila (2 dígitos, 3 si hay más de 99) y nunca del orden de descarga. El encargo manda sobre el `NN.` de la auditoría. Los nombres se limpian de caracteres prohibidos en Windows, se normalizan a NFC y admiten rutas largas. Si el nombre ya existe se añade " (2)": nunca se sobrescribe nada. Toda operación queda en un registro para deshacer.
7. **Carpeta de trabajo del motor**: rutas cortas en `%LOCALAPPDATA%\Tracklister\work\`. El motor descarga con `--name-format "{snum}/{slsk-filename}"`, es decir, una subcarpeta por número de fila de su CSV. Después la app mueve cada archivo a la carpeta del set con su nombre final.
8. **Cuenta de Soulseek**: el usuario y la contraseña van al Administrador de credenciales de Windows (keyring). `settings.json` no guarda ninguno de los dos, y la línea de comandos nunca se escribe sin censurar.
9. **Velocidad**:
   - 4 descargas a la vez, como en tu herramienta vieja;
   - 34 búsquedas cada 220 s, pasadas explícitas;
   - un límite global de la app entre procesos;
   - un proceso del motor por set y por pasada.
10. **Diagnóstico**:
    - busca 5 filas sin descargar por defecto;
    - los compañeros (peers) aparecen como peer-1, peer-2...;
    - tu usuario, tu contraseña y tu IP se censuran.
11. **Aviso de actualización**: una vez al día como mucho, contra `releases/latest`. Solo muestra un aviso con enlace; no instala nada.
12. **"Copiar tracklist"**: una línea por pista, `01. 00:00 Artista - Titulo (Version) [Sello]`. Sin tiempo conocido, se omite.
13. **Informe por set**: `Informe - <set>.txt`, en español, junto a la música.
14. **Tema por defecto, icono y logo**: tema Hormigón, icono con el monograma "T" y logo sin la marca "OR". Las alternativas ya están hechas; ver M.1 a M.3.
15. **Entorno**:
    - Python 3.13.2, el único instalado en el portátil;
    - PySide6-Essentials 6.12.0 en lugar del PySide6 completo, que es más pesado;
    - sin pandas ni scipy en la app.
    - Empaquetado: PyInstaller onedir sin UPX, en un zip.
16. **Motor en el zip**:
    - va el motor fijado, con su LICENSE y el enlace al código del tag exacto;
    - el workflow de GitHub Actions adjunta también el zip del código fuente al Release;
    - va yt-dlp.exe (licencia Unlicense).
17. **Modo simulado del motor real** (`--mock-files-dir`): el código de los dos motores demuestra que en ese modo no se crea el cliente de Soulseek, así que no hay ninguna conexión. Cada motor se ejecutó una vez en este portátil en ese modo, con un usuario y una contraseña de prueba, para comprobar su línea de comandos real y el formato de sus salidas. Los detalles, con archivo y línea, están en `third_party/engines/ENGINE-FACTS.md`. Todas las pruebas automáticas usan el motor falso.

## D. Motor (construcción)

1. **Contraseñas que empiezan por `-`**: los dos motores partirían un valor como `-abc` en `-a -b -c`. En ese caso la app pasa `--pass=-abc` (y lo mismo con el usuario), que los dos aceptan.
2. **Los motores escriben tu usuario** en su salida ("Logging in as ..." / "Login ..."). La app lo censura en todo lo que muestra y reescribe censurado el `engine.log` de cada pasada. La contraseña no la escriben nunca.

## E. Entradas, enriquecimiento y avisos (construcción)

### Texto pegado y comentarios de YouTube

1. **Filas "revisar"**: además de las líneas sin separador artista-título, también pasan a "revisar" (desmarcadas, confianza 0,4) las líneas con 3 o más partes ("Artista - Título - Algo - Otro") y las de artista "ID" con título real. Es la definición de 02 §5.10; el plan solo nombraba las líneas parciales.
2. **MixesDB** `[12] Artista - Título`: el número entre corchetes son minutos (12 → 00:12:00). `[??]` es un tiempo desconocido. Si un texto trae `[1]`, `[2]`, `[3]`... consecutivos, se entiende que es una numeración y no minutos.
3. **Sello con arroba**: `Título (Remix) @ SDL records` → sello "SDL records". Hace falta un espacio después de la arroba, así que una mención tipo `@usuario` no se toma por sello.
4. **`(@150 bpm)`** y parecidos se guardan como nota, no como sello.
5. **Versión tras un feat**: `Título (feat. X) Y Dub` → título "Título", feat "X", versión "Y Dub". Arregla la única fila mal leída del set de andré dancekowski.
6. **Fixtures de YouTube**: son copias de los metadatos que guardó la investigación (5 sets + 1 vídeo sin tracklist + 1 mix de SoundCloud). A cada comentario se le quitaron los campos que el parser no usa (`id`, `parent`, `author_id`, `timestamp`); se conservan el texto, el autor y los likes, que son públicos y necesarios para elegir el comentario. Si prefieres no publicar comentarios de terceros en el repo, se pueden sustituir por textos sintéticos (los tests de elección perderían el contraste con sets reales).

### Tablas, CSV de trackid, limpieza y combinación de fuentes

7. **Orden de las filas**: manda el orden de la tabla. La columna Pos solo reordena si todas las filas tienen un número válido y sin repetir; si falta en alguna fila (el caso que rompía el renombrador viejo), se usa el orden de la tabla.
8. **Codificaciones**: UTF-8 con y sin BOM y Windows-1252, como pide el encargo, y además UTF-16 (lo que Excel guarda como "Texto Unicode", separado por tabuladores).
9. **Tabla sin cabecera**: si ninguna columna tiene un nombre conocido, la 1.ª se toma como artista y la 2.ª como título, con un aviso para revisarlo. Una tabla de una sola columna se lee como "Artista - Título" por celda.
10. **Columna "Time"/"Tiempo"**: es el inicio en el set si sus valores crecen y pasan de 20 minutos; si no, es la duración de la pista (los programas de DJ exportan "Time" = duración).
11. **Fila sin artista**: queda en "revisar" y desmarcada. Nunca se busca solo por el título.
12. **Título y versión**: se separan con la misma regla que usa la verificación al leer las etiquetas del archivo. "(Original)" cuenta como original; "(Extended)" solo cuenta como versión "Extended". Si se quita del título un paréntesis que no es versión ni sello ni feat, por ejemplo "(Part 2)", queda anotado en las notas de la fila.
13. **Pistas repetidas en el set**: se anotan con "repetida (fila N)" y salen como aviso, pero no se desmarcan.
14. **Combinar dos fuentes**: la base (trackid) manda en los nombres. Una pista de la otra fuente se empareja por nombre parecido a cualquier distancia, o por un nombre algo menos parecido si está a ±60 s ("PAS" = "Planetary Assault Systems"). Si una fila "revisar" de la base coincide con una fila buena de la otra fuente, se corrige con ella (queda anotado). Las filas ID de la otra fuente que no caen en un hueco se añaden en su minuto.
15. **Archivos .txt**: se leen como texto pegado, salvo que tengan 2 o más columnas con nombres reconocibles.
16. **Botón "Abrir enlace"**: la importación devuelve los enlaces útiles (la página de trackid.net, 1001tracklists, MixesDB o la tracklist externa que enlaza la descripción de un vídeo), como pide el flujo de 02 §4.

### yt-dlp (enlaces de YouTube y SoundCloud)

17. **Opciones de yt-dlp añadidas** a las del plan, para que el resultado no dependa del PC de cada amigo:
    - `--ignore-config`: no lee una configuración de yt-dlp que el usuario tenga de antes;
    - `--no-playlist` y `--flat-playlist`: un enlace con `&list=...` lee solo ese vídeo, y una lista entera no se pone a leer cientos de vídeos;
    - `--ignore-no-formats-error`: si YouTube no da los formatos (pasa sin el runtime JS que pide yt-dlp), la descripción y los comentarios se leen igual. La sonda de 02 ya usaba esta opción;
    - `--` antes del enlace, y solo se aceptan enlaces http(s).
18. **Desplegable de candidatos**: cada opción trae ya sus filas limpias y su origen, así que cambiar de comentario no vuelve a llamar a yt-dlp. Los comentarios sin tiempos reciben los tiempos de otro comentario que coincide ("ts de @..."), igual que el ganador.
19. **Vídeo sin tracklist**: si la descripción enlaza una tracklist externa ("Read the tracklist here: https://..."), sale un botón para abrirla y el mensaje pide copiarla y pegarla.
20. **Errores de yt-dlp**: el mensaje general es "No se pudieron leer los comentarios de YouTube: actualiza yt-dlp en Ajustes". Un vídeo privado o borrado tiene su propio mensaje, porque actualizar no lo arregla.

### Enriquecimiento (iTunes → Deezer → MusicBrainz) y aviso de actualización

21. **Ritmo de peticiones**: iTunes, 3 s entre peticiones (su límite ronda las 20 por minuto); Deezer, 0,2 s; MusicBrainz, 1 s. La pausa se cuenta desde que llega la respuesta anterior, así que a MusicBrainz nunca le llega más de 1 petición por segundo.
22. **Qué resultado vale**: el primero aceptado que trae duración, en el orden iTunes → Deezer → MusicBrainz. Nunca se acepta otra versión; en esto es más estricto que la prueba de 02, que aceptaba "versión distinta". Si la fila no dice versión, se prefiere "Original Mix" a "Extended Mix".
23. **Duración puesta por el usuario** (una columna "Duración" de su Excel): no se sobrescribe; el enriquecimiento solo añade los identificadores y la confirmación.
24. **Corrección del artista**: solo con iTunes y Deezer, solo si el primer artista de la tienda es uno de los artistas de la fila (así nunca cambia a quién se busca en Soulseek) y quitando el sello si la tienda lo acredita. Ejemplos con datos reales: "STIPP" pasa a "STIPP & Sandrien"; "Roll Dann, Laster Records" pasa a "Roll Dann", porque iTunes acredita "Roll Dann & Laster Records" y "Laster Records" es el sello. El nombre anterior queda en las notas.
25. **Caché**: los resultados se guardan sin caducidad. Un "sin resultados" se vuelve a preguntar pasada una semana, por si la pista sale a la venta. Un error de red no se guarda.
26. **Aviso de actualización**: la petición diaria lleva el ETag (un 304 no gasta el cupo de GitHub). Ante un 403 o 429 (límite de peticiones) o un 404 (todavía no hay release) espera al día siguiente. Sin conexión, vuelve a probar en el siguiente arranque. Mientras `GITHUB_OWNER` siga siendo el marcador, no se envía nada. Al rellenar `GITHUB_OWNER` también queda bien la URL del User-Agent que ve MusicBrainz.
27. **Respuestas grabadas para los tests**: se grabaron una vez desde este portátil con `tools/record_http_fixtures.py` (72 GET públicos a iTunes, Deezer y MusicBrainz: solo artista y título, con el User-Agent de la app, al menos 1,2 s entre peticiones y 0 errores) y se recortaron a los campos que se leen. Las de GitHub (`releases/latest`: versión nueva, igual, 304, 403 y 404) están escritas a mano con la forma documentada.

## G. Interfaz (construcción)

1. **Idioma**: la interfaz usa tildes y eñes (Diagnóstico, Contraseña, Título...). Los mensajes que vienen del motor, de la verificación y de los informes siguen sin tildes ("cancion", "version", "se pedia"); ver N.5.
2. **Primer inicio**: pide tu cuenta de Soulseek (va al Administrador de credenciales de Windows), la carpeta de la biblioteca (por defecto `Música\Tracklister`), el preset y el puerto (49998), y muestra el aviso de compartir con Nicotine+ y una nota legal con la casilla "Entendido". No prueba el inicio de sesión: desde este portátil no se puede conectar a Soulseek, y en casa la primera descarga o el Diagnóstico dicen claramente si el usuario o la contraseña fallan.
3. **Pista repetida**: se pregunta cada vez, con "Usar el que ya tengo (copiar a este set)", "Descargar de nuevo en este set" y la casilla "Aplicar a todos los repetidos de este set". Si hay varias copias en la biblioteca, se elige cuál en un desplegable. Si cierras el diálogo sin elegir, no empieza la descarga y no se copia nada. "Aplicar a todos" usa la primera copia de la biblioteca para cada repetida.
4. **Lista de MP3**: si faltan pistas en lossless, se pregunta una vez por set con todas marcadas; "No, dejarlas sin descargar" no busca ninguna en MP3.
5. **Completar datos**: con el ajuste activado (por defecto), se completa solo después de cada importación; el botón "Completar datos" lo repite. Se trabaja sobre una copia de las filas, así que la tabla no se toca mientras tanto.
6. **Segunda tracklist**: si la tabla ya tiene pistas, al importar otra se pregunta "Reemplazar la tabla" o "Combinar con la actual". "Añadir otra fuente del mismo set" combina un archivo o lo pegado.
7. **Edición de la tabla**: si escribes "Título (X Remix)" en Título, la versión pasa a su columna; una fila ID con artista y título pasa a ser normal y se marca; una fila nueva se marca al ponerle título; una fila sin título no se puede marcar. Subir, bajar, añadir o quitar filas renumera: el número de fila es el NN del archivo.
8. **YouTube/SoundCloud**: se muestra la tracklist elegida con sus alternativas en un desplegable ("Comentario de @x · 22 pistas con tiempos · 11 likes"). Si no hay ninguna clara, se ofrecen las dudosas y el enlace de la descripción.
9. **Carpeta Descargas**: solo se avisan los CSV que aparecen con la app abierta (los que ya estaban se ignoran) y que el importador reconoce como de trackid.net. El aviso tiene "Importar".
10. **Resultados**: cada pista lleva icono y texto de su estado; debajo de la tabla sale el detalle completo de la pista seleccionada (motivos, archivo, origen). "Abrir un set anterior…" reabre una carpeta de set para reintentar más tarde. Si cancelas, se guarda lo hecho y aparece "Continuar descarga".
11. **Reordenar carpeta existente**: las coincidencias dudosas empiezan desmarcadas. Antes de renombrar se pide confirmación. "Deshacer" solo deshace un reordenado, nunca una pasada de descarga de un set de Tracklister.
12. **Diagnóstico**: usa las primeras 5 pistas marcadas de la tabla de Nuevo set (o un archivo), y solo busca, salvo que marques "Descargar también". El informe se guarda además en `%LOCALAPPDATA%\Tracklister\logs\Diagnostico_<fecha>.txt`.
13. **Ajustes**: los cambios se guardan al momento; la cuenta, solo con "Guardar cuenta". El puerto es un campo de texto y no una rueda numérica, para que la rueda del ratón no lo cambie sin querer.
14. **Actualizaciones**: se comprueba 1,5 s después de abrir (nunca en el primer inicio), como mucho una vez al día. "Buscar actualizaciones" en Ajustes la fuerza. Solo muestra un aviso con enlace.
15. **Ventana**: título "Tracklister"; la cabecera muestra "Tracklister by Blessel" con su logo, sobre la textura de hormigón. Si cierras durante una descarga, se pregunta; si sales, se cancela y se guarda lo hecho.

## M. Marca (pendiente de que la confirmes)

1. **Tema por defecto**: Hormigón (`tokens.json` → `default_theme`). Noche está disponible en Ajustes. Para elegir, mira `construccion\capturas\00-vista-general.png`.
2. **Icono de la app**: monograma "T" (Inter Bold, proporciones medidas), tinta sobre el gris del logo. Alternativa guardada: ranuras verticales (`assets/icon/alt/tracklister-alt.ico`).
3. **Logo Blessel**: por defecto sin la marca "OR"; la versión con "OR" está en `assets/logo/alt/`.
4. **Acento único**: el azul gris de la lámpara de su portada de Mixcloud (Hormigón `#294654`, Noche `#5691ac`). El verde `#c8f542` de MavelPoint no se usa: es el tema de la plataforma, no su color.
5. **Colores de estado** con contraste de texto (4,5:1 o más sobre fondo y superficies; 3:1 o más sobre la selección); siempre con icono propio y etiqueta, nunca solo color.
6. **Fuentes incluidas**: Inter 4.1 (interfaz y títulos) y JetBrains Mono 2.304 (tiempos y datos), OFL 1.1, con sus licencias en `assets/fonts/`.

Detalle de la marca: `construccion\identidad-visual.md`.

## N. Unión final (integración)

1. **Una sola conexión HTTP para toda la ventana**: el enriquecimiento y el aviso de actualización comparten el mismo cliente, así que el ritmo de E.21 (MusicBrainz a 1 petición por segundo como mucho, iTunes unas 20 por minuto) se respeta también entre importaciones seguidas y "Completar datos".
2. **`.gitignore`**: la regla `credentials*` escondía también el código `src/tracklister/engine/credentials.py`. Ahora es `/credentials*` (en la raíz) y `credentials*.json` (en cualquier sitio), y un archivo nuevo del código ya no se queda fuera del repo sin avisar.
3. **Comprobación de secretos antes de publicar**: `.\.venv\Scripts\python.exe tools\secrets_scan.py` revisa todo lo que se publicaría en GitHub y solo cuenta, sin enseñar nunca ningún valor: claves y tokens, cuentas escritas (líneas `usuario =`/`password =`, `--user`/`--pass` con valor, `"password": "..."`), y el nombre de la cuenta de Windows y del PC donde se ejecuta. Tiene que salir todo a 0 (hoy sale 0). Un test hace lo mismo en cada ejecución y otro comprueba que una descarga completa con el motor falso, el informe y el Diagnóstico no escriben la cuenta en ningún archivo.
4. **Pruebas de la unión** (`tests/integration/`): la ventana real con el importador, el enriquecimiento (respuestas grabadas), el aviso de actualización (GitHub simulado) y el motor falso, de la tracklist a la carpeta ordenada; y un set con nombres raros dentro de una carpeta tan profunda que las rutas pasan de 260 caracteres.
5. **Textos del motor y de los informes sin tildes**: se quedan así en la v1.0. Se entienden y no rompen nada, pero se nota la diferencia con el resto de la interfaz. Unificarlos es un cambio de textos que toca muchos tests; si quieres, va en la 1.0.1.
