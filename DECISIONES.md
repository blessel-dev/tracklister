# Decisiones tomadas de noche (para confirmar)

Estabas dormido, así que en cada pregunta abierta tomé el valor recomendado y lo apunto aquí. Si quieres cambiar alguna, dime la letra y el número (por ejemplo "G.4") y lo ajusto.

Fuentes: encargo `04-encargo-construccion.md` (Addendum), auditoría `01-auditoria-actual.md` §5 y fuentes `02-fuentes-tracklists.md` §5. Las secciones A a C responden a esas preguntas. Las demás recogen lo que se decidió al construir cada parte: D (motor), E (entradas y enriquecimiento), G (interfaz), M (marca), N (unión final de todo), P (empaquetado y publicación), R (arreglos de la auditoría externa, ronda 1), S (ronda 2), T (ronda 3) y U (ronda 4). T.4 y U.8 tienen la lista de lo que queda para la v1.0.1.

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
7. **Huecos de trackid de más de 90 s**: se convierten en filas "ID (hueco)", desmarcadas. También antes de la primera pista y después de una fila sin hora de fin (ver S.11).
8. **Si dos fuentes discrepan**: trackid manda en los nombres; YouTube rellena huecos e IDs. La diferencia queda en "notas".
9. **Mixcloud**: la v1.0 solo genera el texto para copiar. La publicación por API va en la v1.1.
10. **Filas "revisar"**: desmarcadas, salvo que el enriquecimiento las confirme.

## C. Otros valores por defecto del encargo y de la construcción

1. **Lossless**: se pide FLAC/WAV/AIFF. Si una pista solo existe en MP3, se pregunta una vez por set, con una lista de casillas de esas pistas. Solo las marcadas se buscan en MP3 320. Cada pista se pregunta una sola vez en ese set, también si el set se vuelve a descargar más tarde (S.12).
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
14. **Tema por defecto, icono y logo**: tema Hormigón, icono con el monograma "T" y logo sin la marca "OR". Confirmados por ti el 9 oct; ver M.1 a M.3.
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

1. **Contraseñas que empiezan por `-`**: los dos motores partirían un valor como `-abc` en `-a -b -c`. En ese caso la app pega el valor a la opción con un `=` (`--pass=<valor>`, y lo mismo con el usuario), que los dos aceptan.
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

1. **Idioma**: toda la app escribe en español con tildes y eñes (Diagnóstico, Contraseña, Título...), también los motivos de cada pista, el informe del set y el del Diagnóstico (ver N.5). Los nombres de archivo y de carpeta que crea la app por su cuenta (`Diagnostico_<fecha>.txt`, `_dudosos`, `_originales`) van sin tildes.
2. **Primer inicio**: pide tu cuenta de Soulseek (va al Administrador de credenciales de Windows), la carpeta de la biblioteca (por defecto `Música\Tracklister`), el preset y el puerto (49998), y muestra el aviso de compartir con Nicotine+ y una nota legal con la casilla "Entendido". No prueba el inicio de sesión: desde este portátil no se puede conectar a Soulseek, y en casa la primera descarga o el Diagnóstico dicen claramente si el usuario o la contraseña fallan.
3. **Pista repetida**: se pregunta cada vez, con "Usar el que ya tengo (copiar a este set)", "Descargar de nuevo en este set" y la casilla "Aplicar a todos los repetidos de este set". Si hay varias copias en la biblioteca, se elige cuál en un desplegable. Si cierras el diálogo sin elegir, no empieza la descarga, no se copia nada y no se crea la carpeta del set (S.9). "Aplicar a todos" usa la primera copia de la biblioteca para cada repetida. Solo se ofrecen las copias que vale el formato del set (S.1).
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
14. **Actualizaciones**: se comprueba 1,5 s después de abrir, como mucho una vez al día. Nunca con la pantalla de primer inicio delante; al terminarla, 1,5 s después, sí (S.10). "Buscar actualizaciones" en Ajustes la fuerza. Solo muestra un aviso con enlace.
15. **Ventana**: título "Tracklister"; la cabecera muestra "Tracklister by Blessel" con su logo, sobre la textura de hormigón. Si cierras durante una descarga, se pregunta; si sales, se cancela y se guarda lo hecho.

## M. Marca

Los puntos 1 a 3 están **confirmados por ti** (9 oct, 07:25). El resto sigue pendiente de que lo confirmes.

1. **Tema por defecto: Hormigón (confirmado)**, el gris, porque va más con el branding de Blessel (`tokens.json` → `default_theme`). Un archivo de ajustes nuevo abre en Hormigón.
   - **El selector de tema de Ajustes se queda (confirmado)**: cada usuario puede elegir Noche; se aplica al momento y se guarda para el siguiente arranque. Lo comprueban `tests/gui/test_settings_page.py::test_fresh_settings_show_hormigon` y `::test_noche_persists_after_a_restart`.
2. **Icono de la app: monograma "T" (confirmado)** (Inter Bold, proporciones medidas), tinta sobre el gris del logo. La alternativa con ranuras verticales se queda guardada en `assets/icon/alt/tracklister-alt.ico`, sin usar.
3. **Logo Blessel: sin la marca "OR" (confirmado)**; la versión con "OR" se queda guardada en `assets/logo/alt/`, sin usar.
4. **Acento único**: el azul gris de la lámpara de su portada de Mixcloud (Hormigón `#294654`, Noche `#5691ac`). El verde `#c8f542` de MavelPoint no se usa: es el tema de la plataforma, no su color.
5. **Colores de estado** con contraste de texto (4,5:1 o más sobre fondo y superficies; 3:1 o más sobre la selección); siempre con icono propio y etiqueta, nunca solo color.
6. **Fuentes incluidas**: Inter 4.1 (interfaz y títulos) y JetBrains Mono 2.304 (tiempos y datos), OFL 1.1, con sus licencias en `assets/fonts/`.

Detalle de la marca: `construccion\identidad-visual.md`.

## N. Unión final (integración)

1. **Una sola conexión HTTP para toda la ventana**: el enriquecimiento y el aviso de actualización comparten el mismo cliente, así que el ritmo de E.21 (MusicBrainz a 1 petición por segundo como mucho, iTunes unas 20 por minuto) se respeta también entre importaciones seguidas y "Completar datos".
2. **`.gitignore`**: la regla `credentials*` escondía también el código `src/tracklister/engine/credentials.py`. Ahora es `/credentials*` (en la raíz) y `credentials*.json` (en cualquier sitio), y un archivo nuevo del código ya no se queda fuera del repo sin avisar.
3. **Comprobación de secretos antes de publicar**: `.\.venv\Scripts\python.exe tools\secrets_scan.py` revisa todo lo que se publicaría en GitHub y solo cuenta, sin enseñar nunca ningún valor: claves y tokens, cuentas escritas (líneas `usuario =`/`password =`, `--user`/`--pass` con valor, `"password": "..."`), y el nombre de la cuenta de Windows y del PC donde se ejecuta. Tiene que salir todo a 0 (hoy sale 0). Un test hace lo mismo en cada ejecución y otro comprueba que una descarga completa con el motor falso, el informe y el Diagnóstico no escriben la cuenta en ningún archivo.
4. **Pruebas de la unión** (`tests/integration/`): la ventana real con el importador, el enriquecimiento (respuestas grabadas), el aviso de actualización (GitHub simulado) y el motor falso, de la tracklist a la carpeta ordenada; y un set con nombres raros dentro de una carpeta tan profunda que las rutas pasan de 260 caracteres.
5. **Tildes también en los mensajes del motor y en los informes**: los motivos que ves en Resultados ("Otra versión: se pedía la original..."), el `Informe - <set>.txt` y el informe del Diagnóstico estaban escritos sin tildes ("cancion", "contrasena") y no casaban con el resto de la interfaz. Ahora van bien escritos. Los valores internos que se guardan en `set.json` (por ejemplo el tipo de duda `version`/`duracion`) no cambian, así que los sets ya creados se siguen abriendo igual.
6. **Un archivo dudoso nunca muestra una confianza alta**: antes, un archivo con otra versión, otra canción o una duración que no cuadra podía salir como "Dudoso · otra versión" con "Confianza 100/100", porque la cifra solo medía artista, título y duración. Ahora, en esos casos (los que van a `_dudosos`, y también un archivo truncado) la confianza se queda como mucho en 49/100, por debajo de la franja "revisar" (50-79). Un archivo correcto pero con posible lossless falso se queda como mucho en 79/100. Así, "Dudoso" siempre va con una confianza por debajo del 80 que hace falta para "Verificado". El Diagnóstico aplica la misma regla a los candidatos que rechaza por versión, artista, título o duración.
7. **"Descargar" completa antes las duraciones que faltan**: sin duración esperada, el motor no puede filtrar por duración y la comprobación posterior no detecta un radio edit o un extended (causa P1.2 de la auditoría). Con "Completar datos al importar" activado (por defecto), al pulsar "Descargar" se completan primero las pistas marcadas que aún no tienen duración (por ejemplo, las que has añadido o cambiado a mano después de importar), con el progreso en el aviso de arriba. Las que no aparecen en iTunes, Deezer ni MusicBrainz se descargan igual y en Resultados dicen "Sin duración esperada". Si no hay conexión, la descarga empieza igual. Si desactivas "Completar datos" en Ajustes, se respeta y se descarga directamente.

## P. Empaquetado y publicación

1. **El programa**: PyInstaller en modo carpeta (onedir), con ventana y sin consola, sin UPX y con el icono "T" (`packaging/tracklister.spec`). `Tracklister.exe` lleva sus datos de versión: producto "Tracklister" 1.0.0, sin "Blessel" en el nombre. Se construye con `.\.venv\Scripts\python.exe packaging\build.py --zip`.
2. **scipy y sklearn no van dentro**: la app no los usa (solo los usan las herramientas de marca). El análisis de PyInstaller no los encuentra, y un test comprueba que ningún módulo de `src/` importa nada de lo que se excluye (scipy, sklearn, Pillow, pytest...). Por eso no hacen falta las opciones `--collect-submodules scipy._external --collect-submodules scipy`. Si algún día la app usa scipy, el test avisa: hay que quitarlo de la lista de excluidos y añadir esas opciones.
3. **Qué hay en la carpeta (y en el zip)**: unos 220 MB descomprimidos y 134 MB en zip.
   - `Tracklister.exe` y `_internal\` (Python, Qt y la marca).
   - `engines\`: los dos motores fijados por SHA-256, Sockseek 3.0.5 (por defecto) y sldl 2.6.0 (reserva, Ajustes > Motor), cada uno con su LICENSE y su SOURCE.md. La app los descomprime y los comprueba la primera vez que descarga.
   - `tools\yt-dlp.exe` con sus licencias, que la app copia al primer arranque a `%LOCALAPPDATA%\Tracklister\tools\`.
   - `licenses\`: los textos de licencia de Python, PyInstaller, OpenSSL, Qt/PySide6 y cada paquete de Python que va dentro.
   - `LICENSE.txt` y `NOTICES.txt`, que se abren con doble clic. En el repo siguen siendo `LICENSE` y `third_party/NOTICES.md`.
4. **yt-dlp fijado**: la versión 2026.08.19 (la última estable), fijada por SHA-256 y contrastada con el `SHA2-256SUMS` de su release. Si YouTube cambia, "Actualizar yt-dlp" en Ajustes la pone al día sin tocar la app.
5. **Licencia**: `LICENSE` es el texto oficial de la GPL-3.0 (lo comprueba un test por su SHA-256). "O cualquier versión posterior" consta en `pyproject.toml`, en el README y en `NOTICES`. Qt/PySide6 se usan bajo su opción LGPL-3.0, y su texto va incluido.
6. **Logo y nombre Blessel**: `NOTICES` dice que son la firma del creador y que, como permite la sección 7(e) de la GPL-3.0, la licencia no da derechos de marca sobre ellos. Pendiente de que lo confirmes.
7. **GitHub Actions** (`.github/workflows/release.yml`):
   - Solo se ejecuta al subir una etiqueta `v*`, en un runner `windows-2025`.
   - Las acciones van fijadas por commit: `actions/checkout` v7.0.1 y `actions/setup-python` v7.0.0. La Release se publica con la herramienta `gh` del propio runner, sin acciones de terceros, y el único permiso de escritura es `contents: write`.
   - Pasos: Python 3.13, venv con los locks exactos, motores y yt-dlp comprobados por SHA-256, todos los tests, la build, la prueba de humo sin Python y, al final, la Release.
   - La Release lleva el zip de la app, los zips de código fuente de los dos motores (que exigen la AGPL y la GPL) y `SHA256SUMS.txt`. Las notas, en español, explican cómo comprobar el SHA-256 con `Get-FileHash` y cómo pasar el aviso de SmartScreen.
8. **La etiqueta tiene que coincidir con la versión de la app** (`v1.0.0` con `1.0.0`). Si no coincide, no se publica nada: un exe con otra versión haría que el aviso de actualización saliera siempre.
9. **Propietario de GitHub**: sigue siendo el marcador `OWNER_PLACEHOLDER` en `GITHUB_OWNER` (`src/tracklister/config.py`), la única constante. Lo recomendable es rellenarlo antes de publicar. Si se te olvida, el workflow lo rellena solo para esa build con el dueño del repo y deja un aviso en la ejecución. El repo no cambia, y un fork conserva el propietario que ya tenga.
10. **Dos tests ajustados**: comprobaban que `GITHUB_OWNER` valía el marcador, así que habrían fallado en cuanto lo rellenaras, y GitHub Actions no habría publicado nada. Ahora ponen ellos el marcador antes de comprobar que no se envía nada.
11. **`.tmp\` nunca sale del portátil**: está en `.gitignore` y no se publica, y `build.py` rechaza un paquete que lo contenga. Lo mismo vale para los tests, scipy, `settings.json`, los `.conf` y los `.log`. Hay tests para todo ello.
12. **Huella de este PC**: `build.py` busca dentro del paquete el nombre de la cuenta de Windows y el del PC, y los dos salen 0. En GitHub Actions esa búsqueda se salta, porque el runner no tiene datos personales.
13. **Prueba de humo del exe** (`packaging/smoke_test.py`):
    - Copia la carpeta fuera del repo y arranca `Tracklister.exe` sin Python en el PATH, sin variables `PYTHON*`, con un usuario nuevo y sin tocar el Administrador de credenciales.
    - Comprueba que se abre el primer inicio, que sale con código 0, que el registro queda limpio y que copia yt-dlp entero.
    - En este portátil pasó con la plataforma real de Windows (3,5 s) y en modo offscreen, el que usa GitHub Actions.
    - La captura está en `construccion\capturas\exe\`. En la copia guardada, la carpeta de la biblioteca, que muestra la ruta real de tu Música, se ve como `C:\Users\<usuario>\Music\Tracklister`.

## R. Arreglos de la auditoría externa (ronda 1, 9 oct)

La auditoría de Claude Code y su revisión (`construccion\auditorias\veredicto-r2.json`) pidieron estos cambios. Entre paréntesis, el número del hallazgo.

1. **"Reintentar fallos" con las pistas de `_dudosos`** (N1): antes el motor volvía a elegir el mismo primer candidato y bajaba otra vez el archivo rechazado, sin decir nada.
   - Las pistas dudosas por otra canción, otra versión o duración van en su propia pasada relajada, con `--banned-users` y los usuarios de Soulseek que ya les dieron un archivo rechazado. Esos nombres se acumulan entre reintentos y se guardan solo en tu PC (`set.json`), nunca en el informe del Diagnóstico.
   - Tu propia cuenta nunca va en esa lista.
   - Si no se sabe de qué usuario vino el archivo, o su nombre lleva una coma o espacios en los extremos (los motores parten la lista por comas y recortan los espacios, así que no se podría vetar), la pista no se vuelve a buscar: volvería el mismo archivo. Se queda en `_dudosos` con un motivo que dice qué hacer: revisar el archivo, o corregir artista, título o versión en la tabla de Nuevo set y volver a descargar.
   - Si un reintento trae un archivo idéntico byte a byte al que ya está en `_dudosos` (otro usuario comparte la misma copia), el motivo lo dice: "Ha vuelto el mismo archivo...".
   - Una pista dudosa conserva su archivo de `_dudosos` y su duda mientras no llegue otro mejor, también si la pasada se cancela o no encuentra nada. Antes, una pasada sin resultado la dejaba como "no encontrada" y perdía la referencia a su archivo.
   - El archivo rechazado nunca se borra: si llega uno bueno, el viejo se queda en `_dudosos` y el informe lo lista (R.7).
2. **Títulos con otros números y artistas parciales** (N2): "Dust 1" frente a "Dust 2" daba 83 % y salía verificado.
   - Si los títulos base no llevan exactamente los mismos números (cifras y caras de vinilo como A1/B2; "01" cuenta como "1"), es otra pista: duda de identidad y a `_dudosos`, también sin duración esperada.
   - Un número de pista pegado al nombre del archivo ("01 Spirit.flac", "01 Fjaak - Spirit.mp3") no cuenta como número del título. "808 State" y "2 Unlimited" siguen bien.
   - Artista: se compara artista por artista ("Fjaak" frente a "Fjaak, Chris Liebing" sigue siendo 100). Una coincidencia parcial ("Systems" por "Planetary Assault Systems") solo cuenta si el nombre más corto tiene 2 palabras o más.
   - La misma regla vale para la descarga, para "Reordenar carpeta existente" (una carpeta con solo "Dust 2" no se empareja con la fila "Dust 1") y para las explicaciones del Diagnóstico.
3. **MP3 sin cabecera CBR/VBR** (N3): sin el frame Xing/Info/VBRI, mutagen solo da el bitrate del primer frame, así que un VBR que empieza a 320 pasaba por CBR. Ahora se leen los frames del principio y de hacia el 25, 50 y 75 % del archivo: solo vale si todos tienen el mismo bitrate y llega al mínimo. Si varían, "no cumple formato" (MP3 VBR); si no se pueden leer, también: nunca se acepta en silencio. Vale para todos los presets que admiten MP3.
4. **"CDJ antiguos" con archivos dañados** (B1): un FLAC truncado tumbaba toda la descarga.
   - Un archivo con duda de identidad, versión o duración (también el truncado) no se convierte: va tal cual a `_dudosos` con su número, sin AIFF y sin copia en `_originales`.
   - Si la conversión a AIFF falla (un FLAC dañado cerca del final), la pista queda "no cumple formato" con el motivo, sin dejar nada a medias.
   - Si un archivo no se puede mover o guardar, solo esa pista queda "fallida" con su motivo; las demás de la pasada y las pasadas siguientes siguen.
   - Pase lo que pase, ninguna pista se queda "en curso" y el registro para deshacer se cierra.
5. **Un solo motor a la vez** (N6): no se puede empezar una descarga, "Reintentar fallos" ni "Continuar descarga" con un Diagnóstico en marcha, ni al revés. Los dos entrarían con la misma cuenta y el mismo puerto, y Soulseek cortaría uno. Sale el aviso "Espera a que termine el Diagnóstico (o cancélalo)."
6. **Un archivo reutilizado conserva su marca** (N8): la biblioteca guarda la marca "posible lossless falso" de cada archivo (un `library.json` antiguo sin ella se sigue leyendo). Al elegir "Usar el que ya tengo", la pista sale como "Ya en biblioteca · posible lossless falso", con un motivo que dice de qué set viene, y el informe del set lo marca. El diálogo de repetidos también lo dice.
7. **Re-ejecuciones** (N5): al reordenar la tabla, la copia de `_originales` cambia de número junto con su AIFF, en el mismo registro para deshacer. El informe del set lista, sin borrarlos, los archivos de audio de la carpeta, de `_dudosos` y de `_originales` que ya no son de ninguna pista de la tabla (filas borradas o intentos anteriores).
8. **"Personalizado" con 256 o 192 kbps** (N4): es una elección del propio usuario, fuera de la regla de 320. Lossless, CDJ antiguos y Solo MP3 320 siguen pidiendo MP3 CBR de 320 kbps.
9. **La contraseña va en la línea de comandos del motor** (N9): los motores solo aceptan la cuenta así (`--user`/`--pass`) o en un archivo de configuración, y Tracklister nunca escribe tu contraseña en un archivo (por eso `--no-config`). Mientras descarga, otro programa de tu propio PC podría verla en la lista de procesos; nunca se escribe en los registros ni en los informes (salen `***`). Explicado en `entrega\LEEME.md`, «Nota de seguridad: tu contraseña de Soulseek».

## S. Arreglos de la auditoría externa (ronda 2, 9 oct)

La segunda auditoría de Claude Code (`construccion\auditorias\claude-audit-raw-r2.txt`) encontró 4 fallos que bloqueaban (B1-B4) y 14 notas (N1-N14). Entre paréntesis, el número del hallazgo. Todos los arreglos tienen su test, con el motor falso y sin red.

1. **"Usar el que ya tengo" respeta el formato del set** (B1). Antes se ofrecía cualquier copia de la biblioteca: un FLAC en un set «CDJ antiguos» o «Solo MP3 320», o un MP3 en un set «Lossless» sin la pregunta del MP3. Con «Aplicar a todos», además, sin preguntar nada más.
   - Ahora solo se ofrecen las copias que pasarían la misma comprobación de formato que una descarga de ese set. Se leen las cabeceras del archivo; el archivo entero ya se verificó cuando entró en la biblioteca.
   - Un FLAC nunca entra en «Solo MP3 320». Un MP3 solo entra en «Lossless» o «CDJ antiguos» si en ese set ya dijiste que sí al MP3 de esa pista. Un MP3 con menos kbps de los que pide el preset no se ofrece.
   - En «CDJ antiguos», un FLAC de la biblioteca **se convierte a AIFF**, igual que uno descargado: mismo sample rate y bits, tags y carátula, y si pasa de 48 kHz/24 bits baja a 48 kHz/24 bits. La copia del FLAC original va a `_originales\`; el archivo de la biblioteca no se toca. Elegí convertirlo en vez de no ofrecerlo: así te sigue saliendo la pregunta de siempre y no se vuelve a descargar algo que ya tienes.
   - Si el archivo de la biblioteca ya no vale (ha cambiado) o no se puede convertir (está dañado), esa pista se descarga de nuevo, con el motivo.
2. **Informe y tracklist con rutas largas** (B2). `Informe - <set>.txt` y `Tracklist - <set>.txt` se escriben ahora con el prefijo de rutas largas, como la música. Con un nombre de set largo (un título de YouTube) pasaban de 260 caracteres y fallaban en un Windows de serie (`LongPathsEnabled=0`): no se escribían, y la biblioteca no se enteraba de las pistas del set. «Reordenar» lee también así las etiquetas de los archivos.
   - El test (`tests/integration/test_long_paths.py`) ya no depende del registro del PC. Hace que el proceso se comporte como un Windows de serie: `tests/fakes/maxpath.py` rechaza toda ruta de 260 caracteres o más sin el prefijo. Este portátil tiene `LongPathsEnabled=1`; por eso el test anterior pasaba aunque el fallo existiera. Comprobado: con el código anterior, el test nuevo falla justo al escribir el informe.
   - Límite que queda: los archivos de estado del set (`.tracklister\set.json` y `journal.json`) no llevan el prefijo. Solo fallan si la carpeta del set pasa de unos 220 caracteres. Como el nombre del set se corta a 150, eso solo pasa con una carpeta de biblioteca de más de unos 70 caracteres; con `Música\Tracklister` sobra sitio. Si pasa, sale «No se pudo preparar el set» y no se descarga nada.
3. **"Reintentar fallos" con «No cumple formato»** (B3). Pasa lo mismo que con `_dudosos` (R.1): el usuario que mandó el archivo que no cumplía (un MP3 VBR o de menos de 320, un FLAC que no se pudo convertir) va en `--banned-users` del reintento, así que llega otra copia en vez de la misma.
   - Ese usuario sigue vetado para esa pista en los reintentos siguientes, aunque entretanto la pista quede «No encontrada».
   - Si no se sabe de qué usuario vino, la pista no se vuelve a buscar y el motivo lo dice: «No se ha vuelto a buscar: no se sabe de qué usuario de Soulseek vino el archivo que no cumplía el formato…».
4. **"Reordenar" aplica la carpeta de la vista previa** (B4). Antes se podían renombrar los archivos de una carpeta y guardar el deshacer en otra.
   - Si cambias la carpeta después de «Ver propuesta», la propuesta desaparece y hay que pedirla otra vez.
   - «Aplicar cambios» usa siempre la carpeta de la vista previa: la que nombra la confirmación y la que guarda el deshacer.
   - Nunca renombra archivos de fuera de esa carpeta.
5. **El usuario de cada archivo, nunca adivinado** (N1). Antes, si dos pistas de una pasada bajaban archivos con el mismo nombre, las dos se apuntaban al último usuario, y «Reintentar fallos» podía vetar al que no era.
   - Con Sockseek se usa la búsqueda exacta de la pista y la línea de la descarga terminada.
   - Las líneas de sldl 2.6.0 no dicen la búsqueda: se usa el nombre del archivo y, si dos coinciden, su tamaño.
   - Si aun así quedan dos posibles, no se apunta a nadie. Entonces el reintento dice que no sabe el usuario, en vez de vetar a otro.
6. **Comas en el Diagnóstico** (N2). Los dos motores parten la búsqueda `artist=…, title=…` por cada coma, pero vuelven a unir las comas de un valor: «Earth, Wind & Fire» ya llegaba bien. Solo la rompía una coma seguida de `title=`, `artist=`, `length=`… dentro de un nombre. Esa coma se cambia por un espacio, porque Soulseek busca por palabras; las demás se quedan. Comprobado con una copia del analizador de los motores (`Extractors/String.cs`) en el motor falso.
7. **yt-dlp** (N4, N5). Se copia primero a `yt-dlp.exe.part` y luego se renombra: una copia cortada nunca deja un exe a medias que la app daría por bueno. `--ignore-config` va también en `--version` y en «Actualizar yt-dlp» (`-U`).
8. **Ajustes dañados** (N6). Un valor de un tipo que no toca en `settings.json` ya no impide abrir la app: un tema que es una lista, un puerto con letras, un preset desconocido…
   - Ese ajuste vuelve a su valor de serie y los demás se conservan.
   - Nuevo set avisa: «Algunos ajustes no eran válidos y han vuelto a su valor de serie. Revísalos en Ajustes.».
9. **Cerrar la pregunta de una pista repetida no deja nada** (N7). El set no se guarda hasta que respondes todas las preguntas. Si cierras una, no queda carpeta del set, y un set que ya existía se queda exactamente como estaba.
10. **Aviso de actualización también tras el primer inicio** (N8). Antes, la sesión del primer inicio no comprobaba, y el primer aviso llegaba al abrir la app otra vez. Ahora, al terminar la pantalla de primer inicio, la app comprueba 1,5 s después si hay versión nueva (como mucho una vez al día, como siempre). Cambia lo que decía G.14 («nunca en el primer inicio»): sigue sin comprobar mientras esa pantalla está delante.
11. **Huecos de trackid** (N9).
    - Un hueco antes de la primera pista también se convierte en fila "ID (hueco)": el set empieza en 0:00.
    - Una fila sin hora de fin ya no esconde el hueco siguiente: se cuenta que esa pista sonó la mediana de lo que suenan las pistas de ese mismo set. La fila del hueco dice «estimado: la pista anterior no tiene hora de fin en el CSV». Si ninguna fila tiene hora de fin, no se inventa ningún hueco.
    - Con el CSV de muestra y el umbral de 90 s no cambia nada: siguen los 4 huecos.
12. **La pregunta del MP3, una vez por set** (N3). Antes era una vez por descarga, así que «Continuar descarga» podía volver a preguntar por pistas ya respondidas. Ahora el set recuerda qué pistas se preguntaron (`lossy_asked` en `set.json`; los sets anteriores se siguen abriendo). Cerrar la pregunta cancelando la descarga no cuenta como respuesta.
13. **Versiones en el empaquetado** (N10). El exe se puede construir con una versión previa como `1.0.1rc1`: Windows guarda 1.0.1.0 y el texto completo va en la versión del producto. GitHub Actions comprueba además que `pyproject.toml` dice la misma versión que la app; si no, no publica nada.
14. **El Firewall pregunta por el motor, no por Tracklister**. El programa que escucha en el puerto es `sockseek.exe` (o `sldl.exe`, el motor alternativo), y el aviso del Firewall de Windows nombra ese archivo. El texto del puerto (primer inicio y Ajustes) y el informe del Diagnóstico ya lo dicen así; antes decían «permite Tracklister». El LEEME ya nombraba el motor.

### Notas de la auditoría que solo se documentan

15. **El Administrador de credenciales no entra en la prueba de humo del exe** (N11). `packaging/smoke_test.py` arranca el exe con el keyring nulo, para no tocar nunca el Administrador de credenciales de este portátil corporativo. El módulo de Windows de keyring sí va dentro del exe (`keyring.backends.Windows` y `win32ctypes.pywin32.win32cred` están en la lista de módulos de la build, `build\pyinstaller\tracklister\PYZ-00.toc`). Lo prueba de verdad el primer inicio en tu PC de casa, cuando «Empezar» guarda la cuenta; si falla, sale «No se pudo guardar la cuenta…» (LEEME, punto 6). **Pendiente de comprobar en casa.**
16. **Ajustes enseña tu usuario de Soulseek** (N12): «Cuenta guardada: <usuario>», a propósito, para que sepas qué cuenta tienes guardada. La contraseña no se enseña nunca, y el usuario no sale en ningún archivo, informe ni Diagnóstico. **Pendiente de que lo confirmes**; si prefieres que no salga, se cambia por «Cuenta guardada».
17. **Tildes en la salida del motor** (N13): comprobado en el código de los dos motores fijados, no hace falta cambiar nada.
    - Los dos fuerzan su salida a UTF-8 al arrancar (`Console.OutputEncoding = System.Text.Encoding.UTF8`: Sockseek 3.0.5 `Sockseek.Cli/Program.cs:25`, sldl 2.6.0 `slsk-batchdl/Program.cs:6`), y Tracklister la lee en UTF-8.
    - Aunque una línea saliera mal, los archivos y sus nombres salen bien: mandan los archivos del disco y los datos de tu tabla.
    - `entrega\LEEME.md` ya lo explica en el punto 6 («Letras raras en nombres con tildes o eñes»), así que no lo he tocado.
18. **Las acciones fijadas de GitHub Actions** (N14). `actions/checkout` v7.0.1 y `actions/setup-python` v7.0.0 van fijadas por commit, pero desde este portátil no se puede comprobar que esos commits existan. Si alguno no existe, la ejecución falla al empezar («Set up job»), antes de construir nada, y no se publica nada. El arreglo sería poner el commit de esa etiqueta, que sale en la página de releases de la acción. Se comprueba en la primera ejecución en GitHub.

## T. Arreglos de la auditoría externa (ronda 3, 9 oct)

La tercera auditoría de Claude Code (`construccion\auditorias\claude-audit-raw-r3-1.txt`) confirmó los 21 arreglos de las rondas 1 y 2 y encontró 2 fallos que bloqueaban (B1, B2) y 9 notas (N1-N9). Aquí van B1, B2 y N2, cada uno con sus tests (motor falso, sin red). Las demás notas quedan para la v1.0.1 (T.4).

1. **Un artista con un nombre parecido ya no pasa por el correcto** (B1). Con el mismo título, «Adam Port» por «Adam Beyer» (63 % de parecido), «Chris Lake» por «Chris Liebing» (70 %) o «Ken Faki» por «Len Faki» (88 %) salían como «Verificado». Era justo tu queja principal: canciones equivocadas. Pasaba sobre todo en «Reintentar fallos», que busca sin `--strict-artist`, y también en «Reordenar carpeta existente» y en el Diagnóstico.
   - Ahora el artista se compara palabra por palabra. Cada palabra del nombre tiene que tener su pareja en el otro, el apellido incluido. Las palabras de hasta 4 letras tienen que ser iguales («Len» no es «Ken»); las más largas admiten una errata («Leibing» por «Liebing»). Además, un parecido del nombre entero por debajo del 85 % nunca es el mismo artista. Lo de las rondas anteriores sigue igual: los números del título (R.2) y los artistas parciales de 1 palabra («Systems» no es «Planetary Assault Systems»).
   - Siguen pasando como el mismo artista: mayúsculas («CHRIS LIEBING»), «DJ Rush»/«Dj Rush», «Ø [Phase]»/«O [Phase]», el orden de un dúo («Allatt & Blasha»), un sello o un segundo artista en la etiqueta («Roll Dann & Laster Records» para la fila «Roll Dann», con el sello ya quitado), las tildes («Hector Oaks», «Rodhad») y los espacios («DVS 1»/«DVS1»).
   - **Decisión tomada**: un archivo de otro artista es una duda de identidad. Va a `_dudosos` con el motivo «Otro artista: 'Adam Port' no es 'Adam Beyer' (el nombre se parece un 63 %, pero no coincide palabra por palabra).» y una confianza de 49/100 como mucho, nunca «Verificado». La auditoría también permitía dejarlo en el set como «revisar», pero es otra canción, así que no lo pongo con su número entre las buenas. Como cualquier duda de identidad, el siguiente «Reintentar fallos» veta a ese usuario (R.1) y busca otra copia.
   - Lo que cambia por ser más estricto, y nunca se acepta en silencio: «Duff» y «Duffy» ya no se toman por el mismo artista (el caso del renombrador viejo). Pero también acaban en `_dudosos` una errata en una palabra corta («Amelie Lenz» por «Amelie Lens», «Fjak» por «Fjaak»), una etiqueta con solo el apellido («Klock» por «Ben Klock») o sin el «DJ» («Rush» por «DJ Rush»). Si te pasa, mira el archivo en `_dudosos`. Las transliteraciones alemanas sí pasan («Vaeth» por «Väth»).
   - «Reordenar carpeta existente»: un archivo de otro artista cuenta como si no tuviera artista, así que nunca se propone, ni siquiera con el mismo título. La fila queda «falta» y el archivo «sobra», y se queda como está.
   - Diagnóstico: ese candidato sale «rechazado: otro artista con un nombre parecido ('Adam Port', 63%)», con la misma confianza máxima de 49.
2. **El Diagnóstico ya no deja pasar IP con puerto** (B2). Una dirección IPv4 escrita como `203.0.113.7:2242` (así escribe .NET una conexión), `IP:203.0.113.7` o al final de una frase (`…203.0.113.7.`) salía sin censurar. Ahora hay una pasada solo para IPv4 antes de la general, comprobada con `ipaddress.IPv4Address`: queda `[censurado]:2242`. El puerto se queda, porque no identifica a nadie. Las versiones (`3.0.5`, `2.6.0`), las horas (`01:02:03`), las duraciones y los bitrates no se tocan.
3. **Un fallo al copiar de la biblioteca ya no para la descarga** (N2). Si al elegir «Usar el que ya tengo» la copia al set falla (archivo bloqueado o borrado, disco lleno…), antes se paraba toda la descarga. Ahora solo esa pista se descarga de nuevo, con el motivo «No se pudo copiar a este set el archivo de tu biblioteca (…): se descarga de nuevo.». Lo que ya se había copiado de esa pista se deshace: no queda medio archivo con su nombre final ni una copia suelta en `_originales`. Las demás repetidas se copian como siempre.

### T.4 Para la v1.0.1 (notas de la ronda 3 que no bloquean)

- **N1. Una pista «Usar el que ya tengo» cuyo archivo borras puede quedarse en «Pendiente».** Si después borras el archivo y ya no queda copia en la biblioteca, «Descargar» se la salta aunque el motivo diga «se vuelve a buscar»; solo «Reintentar fallos» la recupera. Arreglo previsto: olvidar la elección al detectar que el archivo falta.
- **N3. Los usuarios vetados se comparten entre pistas.** En «Reintentar fallos», todas las pistas con vetos van en una pasada con una sola lista `--banned-users`: un usuario vetado por la pista A tampoco se usa para la B. Además, un reintento puede lanzar 2 procesos del motor por pasada, uno detrás de otro. Es aceptable; queda documentado aquí.
- **N4. Casos raros del censurado del Diagnóstico.** Una contraseña como `1` o `peer` hace que no se genere el informe (falla cerrado: nunca sale nada sin censurar). Un usuario que forma parte de la ruta de tu carpeta personal estropea el `%USERPROFILE%`, y un usuario de Soulseek llamado como una palabra corriente («de») cambia esa palabra en el texto. Arreglo previsto: censurar primero la carpeta y los usuarios, y estos solo en la columna de rutas.
- **N5. Ajustes comprueba el tipo, no el rango.** `searches_per_time: -5` en `settings.json` rompe el límite de búsquedas, y `listen_port: 80` se guarda y luego no deja pulsar «Empezar» en el primer inicio. Arreglo previsto: comprobar también los rangos.
- **N6. Una versión previa saldría como «la última».** El workflow no publica las etiquetas tipo `v1.0.1rc1` como pre-release, así que GitHub la daría como `releases/latest` y avisaría a todos los de la 1.0.0. Mientras tanto, no subas etiquetas de prueba.
- **N7. Errores del motor sin mensaje en español.** Si la carpeta del motor está bloqueada o su marca está dañada, sale un error técnico en vez de «No se encuentra el motor…».
- **N8. Huecos pequeños de la cuenta y del Diagnóstico.** Un usuario de Soulseek igual a la clave interna del keyring pisaría la contraseña guardada, y los errores del keyring que no son `KeyringError` no se recogen. Un Diagnóstico que falla por un error del motor deja su carpeta de trabajo en `%LOCALAPPDATA%\Tracklister\work\diagnostico`.
- **N9. Lo que ya estaba documentado, sin cambios:** R.8, R.9, el límite de S.2 para `set.json`/`journal.json`, S.15-S.18 (las acciones fijadas de GitHub siguen sin poder comprobarse sin conexión), y las notas N7, N10 y N11 de la ronda 1 (un usuario de Soulseek que es una palabra común, la URL provisional del User-Agent de MusicBrainz antes de publicar, y la carpeta `entrega\`, que es el paso de entrega).
- **Visto al arreglar B1 (no lo señaló la auditoría).** Si un archivo no lleva la etiqueta de artista o la de título, la carpeta del usuario también cuenta como artista. Así que un archivo sin etiquetas de «Adam Port», guardado en una carpeta «Adam Beyer - Selección», pasaría como de Adam Beyer. Hace falta, además, el mismo título. No lo he cambiado: también es lo que deja pasar un «VA - Título» dentro de la carpeta del artista. Arreglo previsto: que la carpeta solo cuente cuando el nombre del archivo no dice ningún artista.

## U. Arreglos de la auditoría externa (ronda 4, 9 oct)

La cuarta auditoría de Claude Code (`construccion\auditorias\claude-audit-raw-r4-1.txt`) y su revisión (`construccion\auditorias\veredicto-r4.json`) confirmaron los 24 arreglos de las rondas 1 a 3 y encontraron 6 fallos que bloqueaban (B1-B6) y 22 notas (N1-N22). Aquí van los seis, cada uno con sus tests (motor falso, sin red), y una nota de la revisión (R4-REV-1). Las demás notas quedan para la v1.0.1 (U.8).

1. **Corregir una fila en Nuevo set ya no deja la canción vieja con el nombre nuevo** (B1). Si después de descargar cambiabas en la tabla el título o la versión de una pista («Strobe» era en realidad «Some Chords», o era el «Kai Remix») y volvías a pulsar Descargar con el mismo nombre de set, la fila conservaba el resultado viejo: no se descargaba nada, el audio de «Strobe» pasaba a llamarse «01 - deadmau5 - Some Chords.flac», «Verificado», y entraba así en la biblioteca.
   - Ahora solo heredan el resultado anterior las filas con el mismo artista, título y versión: las que no has tocado, las que has movido y las que solo cambian el sello o el inicio. Una fila corregida es otra pista: empieza «Pendiente» y se descarga.
   - El archivo viejo no se toca ni se renombra: se queda con su nombre y el informe lo lista entre los archivos que ya no son de ninguna pista (R.7).
   - Dos filas corregidas que antes acababan con el mismo identificador ya no chocan al renombrar.
2. **Un título con una palabra de más o de menos es otra pista** (B2). «Feel It» frente a «Feel It All» (78 %), «Higher» frente a «Higher Love» (71 %), «Feel It» frente a «Feel Me» o «Sin» frente a «Original Sin» salían «Verificado» sin duración esperada. Soulseek los deja pasar: con `--strict-title` basta con que el título pedido esté dentro del nombre como palabras enteras, también en «Reintentar fallos».
   - Ahora el título se compara palabra por palabra, con la regla de los artistas (T.1): cada palabra necesita su pareja en el otro título, sin palabras de más ni de menos. Las palabras de hasta 4 letras tienen que ser iguales; las más largas admiten una errata («Strobbe» por «Strobe»).
   - Siguen siendo el mismo título: mayúsculas, «Rock & Roll»/«Rock and Roll», «Don't Stop»/«Dont Stop», «Pt. 2»/«Part 2», «01»/«1», un número de pista pegado al nombre («01 Feel It.flac»), y todo lo que ya se quitaba del título: «(Original Mix)», « - Original Mix», el sello entre corchetes y el «feat.».
   - **Decisión tomada**: como con los números (R.2), es una duda de identidad: va a `_dudosos` con el motivo «Otro título: 'Feel It All' no tiene las mismas palabras que 'Feel It', así que es otra pista.» y una confianza de 49 como mucho, y el siguiente «Reintentar fallos» veta a ese usuario. «Reordenar carpeta existente» ya no lo propone y el Diagnóstico lo da por «rechazado: título distinto».
   - Lo que cambia por ser más estricto, y nunca se acepta en silencio: un archivo con una palabra suelta de versión sin «Mix» («Spirit - Original», «Spirit - Extended») o con algo pegado al título («Spirit-WEB») acaba en `_dudosos`. Una palabra «Original» que queda en el título cuenta como palabra, por eso «Sin» no es «Original Sin».
   - **Nombres de la «scene»**: en un nombre con guiones bajos en vez de espacios, el grupo que firma la copia va pegado al final con un guion («plug_trax_-_zoned_out-psy.mp3»). Ese final no cuenta como palabra del título, así que «Reordenar» sigue emparejándolo con «Plug Trax - Zoned Out» (el caso A de las pruebas del renombrador viejo, 01 §3). Si ese final es una palabra de versión («-remix», «-live», «-radio»), no se quita.
3. **No se pierde ningún grupo de versión** (B3). «Spirit (Kai Remix) (Extended Mix)» se leía como el Extended Mix de la original, y «Spirit (Live at Awakenings)» como la original: los dos salían «Verificado» para una fila original. Al pegar la tracklist, además, el remix acababa en la columna Sello y se buscaba la original.
   - Ahora, si un título lleva varios grupos de versión, manda el de más a la derecha que no sea la original ni el extended: «(Kai Remix) (Extended Mix)» y «(Extended Mix) (Kai Remix)» son el Kai Remix; « - Kai Remix (Extended Mix)» también. «(Live)» y «(Live at …)» son la versión en directo. Si todos son original o extended, se queda el de más a la derecha, como antes.
   - **Decisión tomada** (cambiada en V.1 y V.3): «(Kai Remix) (Radio Edit)» es el radio edit del Kai Remix. La versión guarda los dos grupos («Kai Remix - Radio Edit») y el archivo tiene que tenerlos los dos. La decisión anterior («es el radio edit», el grupo de más a la derecha) la propuso la revisión r4-1, no tú, y contradecía 04 §8. Desde V.1 se guardan todos los grupos que no son original ni extended, no solo uno.
   - Vale igual para el texto pegado, las tablas, el CSV de trackid, las etiquetas y los nombres de los archivos, la biblioteca, el enriquecimiento (ya no toma la duración de un remix para una fila original), «Reordenar» y el Diagnóstico. En el texto pegado, los otros grupos de versión pasan a las notas de la fila en vez de a la columna Sello.
   - Una fila del Kai Remix sigue aceptando su Extended Mix («Spirit (Kai Remix) (Extended Mix)»).
4. **Un archivo abierto en otro programa ya no deja nombres temporales** (B4). Después de insertar o mover filas, Tracklister cambia los números de los archivos del set. Si uno estaba abierto en Ableton o en un reproductor, el cambio de nombre fallaba a medias: quedaban archivos escondidos como `__tracklister_tmp_…`, el set no se guardaba y, al volver a abrirlo, esas pistas se descargaban otra vez.
   - Ahora es todo o nada: si un cambio de nombre falla, se deshacen los que ya se habían hecho y la carpeta queda exactamente como estaba. Sale «No se pudo cambiar el nombre de '02 - … .flac': está abierto en otro programa (Ableton, un reproductor…). Ciérralo y vuelve a pulsar Descargar.». Al volver a pulsar Descargar con el archivo cerrado, se cambian los nombres sin descargar nada.
   - En Windows, cuando un cambio de nombre falla, Python copia el archivo y luego no puede borrar el original. Esa copia ya no se queda en la carpeta (comprobado con un archivo abierto de verdad en este portátil).
5. **Un disco que se desconecta ya no cuelga la descarga** (B5). Con la biblioteca en un disco USB o de red, si el disco se desconectaba mientras se colocaban los archivos, Tracklister buscaba la carpeta subiendo de nivel sin fin: la descarga se quedaba colgada y «Cancelar» no la paraba.
   - Ahora esas pistas quedan «Fallida» con el motivo «No se pudo mover o guardar el archivo descargado (No se encuentra la unidad de la carpeta del set: ¿se ha desconectado el disco?).» y la descarga termina. Ninguna pista se queda «en curso». Con el disco conectado otra vez, «Reintentar fallos» las vuelve a pedir.
6. **Un WAV o AIFF con un códec con pérdida no es lossless** (B6). Un WAV o AIFF puede llevar dentro audio con pérdida (µ-law, A-law, ADPCM, GSM…). Antes solo se miraba el contenedor, así que pasaba como lossless y en «CDJ antiguos» se ponía tal cual, sin convertir.
   - Ahora solo valen el PCM de 8, 16, 24 y 32 bits y la coma flotante (que en «CDJ antiguos» se sigue convirtiendo a AIFF PCM, como antes). Lo demás queda «No cumple formato» con el motivo «WAV con un códec con pérdida (ULAW): no es lossless.», y «Reintentar fallos» veta a ese usuario (S.3). La biblioteca tampoco ofrece esos archivos.
   - **Decisión tomada**: también se rechaza el DWVW, un AIFF-C comprimido sin pérdida que casi nadie usa y que los CDJ no leen.
7. **Al corregir una pista en la tabla se olvidan sus datos de la tienda** (R4-REV-1, de la revisión; va con B1). Si cambias el artista, el título o la versión de una fila ya completada, se borran la duración y los identificadores que trajo iTunes, Deezer o MusicBrainz, porque eran de la pista anterior. Si no, la fila corregida se buscaba con la duración de la otra pista y salía «No encontrado». Al pulsar Descargar se completan otra vez (N.7). Una duración escrita a mano se respeta (E.23), y cambiar solo mayúsculas, el sello o el inicio no borra nada.

### U.8 Para la v1.0.1 (notas de la ronda 4 que no bloquean)

- **N1. Remezcladores parecidos**: «Kai Remix» frente a «Kaiser Remix», o un remix frente a un dub del mismo remezclador. En la descarga no pasa, porque el nombre del archivo tiene que llevar el remix pedido entero. Arreglo previsto: la regla de palabras también para el remezclador, y el mismo tipo de versión.
- **N2. «(Part 2)» se quita del título** (E.12), así que un «(Part 1)» pasaría. La columna Notas lo avisa antes de descargar («quitado del título: (Part 2)»). Arreglo previsto: dejar «(Part N)» en el título para que cuente su número (R.2).
- **N3. La clave de la biblioteca quita «original»**: «Sin» y «Original Sin» del mismo artista comparten clave. La pregunta de pista repetida sale igual y enseña la copia. La parte de los títulos ya está arreglada en U.2.
- **N4. Versión en la etiqueta frente al nombre**: si la etiqueta dice el remix pedido y el nombre dice «Original», se acepta.
- **N5. Artistas de una palabra larga** admiten una errata («Regal»/«Regalo»), y los nombres de grupo con «&» se parten («Rhythm & Sound»). Es el diseño de T.1 y R.2.
- **N6. Etiquetas «A/B» o «A;B»** no se parten, y solo se lee el primer valor ID3: solo da dudas de más.
- **N7. Extensión**: un WAV llamado `.aiff` se queda `.aiff` (el motivo lo dice, marca `extension_distinta`).
- **N8. «Reordenar» sobre una carpeta de set de Tracklister** no actualiza `set.json`; una descarga posterior volvería a pedir esas pistas.
- **N9. Más robustez de «Reordenar»**: sin vuelta atrás automática si un nombre falla a medias, Deshacer pulsable mientras aplica, los « (2)» se renombran en cada pasada y los cambios de solo mayúsculas no se aplican.
- **N10. `_originales`**: se mueve el original sin comprobar si ya hay uno idéntico (puede dejar « (2)»).
- **N11. «CDJ antiguos» deja los WAV PCM de 8 bits** sin convertir.
- **N12. Nombres reservados de Windows** con varios puntos o `CONIN$`/`CONOUT$` (solo afecta a la carpeta del set).
- **N13. Sin internet, Sockseek reintenta el inicio de sesión sin fin** y el motivo final culpa a la cuenta. «Cancelar» sí lo para. Arreglo previsto: un plazo de 60 a 90 s y el mensaje «sin conexión».
- **N14. Un título como «Login Failed»** se toma por un error del motor.
- **N15. Huecos pequeños al leer la salida del motor** (archivos bloqueados de la 3.x, «: » en nombres remotos, filas no latinas). Todos fallan del lado seguro.
- **N16. Robustez del proceso del motor**: la contraseña en la línea de comandos (R.9), sin Job object de Windows, `taskkill` por el PATH, un `TimeoutError` del límite de búsquedas y el usuario en `engine.log` hasta el final de la pasada.
- **N17. Diagnóstico con una contraseña numérica**: censurar antes de leer el JSON puede dejar una fila como «sin resultados». No se filtra nada.
- **N18. El Diagnóstico no se para ante un error fatal**, y su modo con descarga deja carpetas `diag-set-*`.
- **N19. Censura de IPv6**: no tapa `ip:2001:db8::1` ni una dirección de 8 grupos sin corchetes con puerto. Soulseek usa IPv4 (cubierta en T.2).
- **N20. El aviso de actualización** abre el enlace de la release sin comprobar que sea de `https://github.com/`; solo se llama a `api.github.com`.
- **N21. Rangos de los ajustes** (`searches_per_time`, `searches_renew_s`, `concurrent_downloads`): es T.4 N5.
- **N22. Las notas de la ronda 3 (T.4) siguen igual.**

## V. Arreglos de la auditoría externa (ronda 4, segunda auditoría, 9 oct)

La segunda auditoría de la ronda 4 (`construccion\auditorias\claude-audit-raw-r4-2.txt`) y su revisión (`construccion\auditorias\veredicto-r4.json`, iteración 2) confirmaron 30 de los 31 arreglos de las rondas 1 a 4. Encontraron 3 fallos que bloqueaban (B1-B3), los tres en el mismo sitio: cómo se lee la versión cuando un título trae más de un grupo. Van arreglados con una sola regla para todos los caminos, cada uno con sus tests (motor falso, sin red). Las notas N3-N16 quedan para la v1.0.1 (V.6).

1. **Una sola regla para la versión** (B1-B3). Una sola función de `core/textnorm` (`merge_versions`) decide la versión en todos los caminos. Son el texto pegado y los comentarios de YouTube, los Excel y CSV propios (también su columna Versión/Mix), el CSV de trackid.net y el editor de la tabla (el título y la columna Versión). También las etiquetas y los nombres de los archivos, las tiendas del enriquecimiento, la biblioteca, «Reordenar» y el Diagnóstico.
   - Cuentan todos los grupos de versión del título: los paréntesis y corchetes con una palabra de versión, un «(Extended)» suelto, un « - Kai Remix», un «Original Mix» al final y lo que va después de un feat («Spirit (feat. Jo) Extended Mix (Kai Remix)»), en cualquier orden. La columna Versión/Mix de una tabla es un grupo más, a la derecha.
   - Los grupos original/extended se quitan si queda otro. Si todos son original o extended, se queda el de más a la derecha, como antes.
   - Los demás se quedan todos, en el orden escrito, sin repetidos y unidos con « - ». Un grupo cuyas palabras ya están en otro cuenta como repetido («Remix» junto a «Kai Remix»).
   - «(Kai Remix) (Extended Mix)», «(Extended Mix) (Kai Remix)», «(Kai Remix) (Extended)» y «(Kai Remix) - Extended Mix» siguen siendo el Kai Remix. «(Kai Remix) (Radio Edit)» pasa a ser «Kai Remix - Radio Edit», igual que «(Kai Remix - Radio Edit)». El archivo se llama «01 - Fjaak - Spirit (Kai Remix - Radio Edit).flac», con el patrón de 04 §9.
2. **Una tabla propia ya no pierde el remix** (B1). En un Excel o CSV propio, «Spirit (Kai Remix) (Extended)», «[Extended]» o «Spirit (Kai Remix)» con la columna Mix «Extended Mix» se quedaban en la original extended. Se buscaba «Spirit (Extended)», la original extended salía «Verificado» y «Usar el que ya tengo» la ofrecía de un set anterior. Ahora es el Kai Remix, como en el texto pegado y en el CSV de trackid.
3. **El radio edit de un remix ya no pasa por el de la original** (B2). «(Kai Remix) (Radio Edit)» guardaba solo «Radio Edit». Pasaba lo mismo con «(Edit)», «(Live)», «(Instrumental)» o «(Remastered)». El radio edit de la original salía «Verificado» y la biblioteca lo ofrecía.
   - Ahora la versión se compara grupo a grupo. Cada grupo de la fila necesita su pareja en el archivo, y al revés, sin grupos de más ni de menos.
   - La pareja tiene que ser del mismo tipo (remix, radio edit, edit, dub, directo u otro) y llevar las mismas palabras de versión: «Kai Remix Edit» no es «Kai Remix». Un remix tiene que nombrar al mismo remezclador, como antes. Un radio edit tiene que ser de la misma gente o de nadie: «Kai Radio Edit» no es el «Radio Edit» de la original.
   - Al motor se le pide el título con el primer grupo que nombra un remezclador: «Spirit (Kai Remix)». Así `--strict-title` exige el remix y deja pasar sus edits, que luego separan la verificación y `--length-tol`. Antes se pedía «Spirit (Radio Edit)», que dejaba pasar el radio edit de la original y no el bueno. Con un solo grupo se pide como siempre.
   - La biblioteca y las filas repetidas distinguen «Kai Remix - Radio Edit», «Radio Edit» y «Kai Remix».
   - En el texto pegado, el remezclador ya no va a las notas: va en la versión. Los grupos original/extended que se quitan siguen en las notas.
4. **Un feat seguido de la versión ya no tapa el remix** (B3). En una tabla, «Spirit (feat. Jo) Extended Mix (Kai Remix)» es el Kai Remix con el feat «Jo», y «Spirit (feat. Jo) Kai Remix (Radio Edit)» es «Kai Remix - Radio Edit». En el texto pegado ya era así.
5. **Decisiones tomadas**
   - Cambia la «Decisión tomada» de U.3: «(Kai Remix) (Radio Edit)» es el radio edit del Kai Remix, no un radio edit cualquiera. La decisión anterior la propuso la revisión r4-1, no tú, y contradecía 04 §8 («version-aware: Original/Extended vs Remix vs Radio Edit») y el propio título de U.3.
   - Lo que escribes en la columna Versión del editor sigue la misma regla: «(Kai Remix) (Radio Edit)» queda «Kai Remix - Radio Edit», y «Kai Remix (Extended Mix)» queda «Kai Remix».
   - Lo que cambia por ser más estricto, y nunca se acepta en silencio: van a `_dudosos` como otra versión (y «Reintentar fallos» veta a ese usuario) un «Kai Edit» o un «Kai Dub» para la fila «Kai Remix», un «Kai Remix Edit» para «Kai Remix», un «Instrumental Radio Edit» para «Radio Edit», o un archivo que escribe los dos grupos en uno sin guion («Kai Remix Radio Edit») para la fila «Kai Remix - Radio Edit».
   - Una fila con versiones distintas en el título y en la columna Mix («Dust 1 (Kai Van Dongen Remix)» con Mix «Other Remix») pide los dos grupos y acabará en duda. Corrígela en la tabla antes de descargar.
6. **Para la v1.0.1 (notas N3-N16 de la segunda auditoría, que no bloquean)**:
   - **N3.** El enriquecimiento puede tomar la duración de la original para una fila «Extended Mix» si la tienda no tiene el extended. Original y Extended van juntos (04 §8). Arreglo previsto: dejar esa fila sin duración.
   - **N4.** Versiones escritas con guion que no se separan (« - Live», « - 2011 Remaster»), un sello «[Live At Robert Johnson]» leído como directo y plurales («Dreamer»/«Dreamers»). Solo dan dudas de más. «Spirit (Kai Remix) - Extended Mix» ya se lee bien con V.1.
   - **N5.** Un set «Personalizado» reabierto usa el Personalizado de hoy.
   - **N6.** Casos límite de U.7: una duración escrita después de completar datos se borra al corregir el título. Pasar de la original a «Extended Mix» conserva la duración.
   - **N7.** Tu usuario se censura como subcadena antes de leer las líneas del motor, así que un veto puede no aplicarse. Nunca se acepta nada en silencio.
   - **N8.** Si falla escribir `stdout.txt` (disco lleno), la pasada espera hasta «Cancelar», y «Cancelar» sí la para.
   - **N9.** sldl 2.6.0 (el motor alternativo): con 4 descargas a la vez, dos archivos con el mismo nombre chocan en el temporal. Da un fallo de más que «Reintentar fallos» arregla.
   - **N10.** Personalizado sin formatos marcados y con «preguntar MP3» solo hace la pasada de MP3. `max_bitdepth` no se pasa al motor: esos archivos se rechazan después.
   - **N11.** El aviso de actualización vuelve a probar en cada arranque después de un error de red, no solo sin conexión.
   - **N12.** En «Reordenar», marcar una casilla mientras se aplica vuelve a activar «Aplicar».
   - **N13.** Un `journal.json` dañado hace que «Reordenar» enseñe un aviso en cada tecla.
   - **N14.** La carpeta de la biblioteca del primer inicio admite una ruta relativa.
   - **N15.** Al cerrar durante una descarga, la ventana se cierra después de 30 s aunque el proceso siga.
   - **N16.** U.8 y T.4 siguen igual. La parte de U.8 N1 que pedía el mismo tipo de versión ya está en V.3, y lo de «Kaiser Remix» sigue pendiente.
