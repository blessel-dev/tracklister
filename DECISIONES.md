# Decisiones tomadas de noche (para confirmar)

Estabas dormido, así que en cada pregunta abierta tomé el valor recomendado y lo apunto aquí. Si quieres cambiar alguna, dime el número y lo ajusto.

Fuentes: encargo `04-encargo-construccion.md` (Addendum), auditoría `01-auditoria-actual.md` §5 y fuentes `02-fuentes-tracklists.md` §5.

## A. Preguntas de la auditoría (01 §5)

1. **Motor**: Sockseek 3.0.5, fijado por SHA-256, detrás de un único adaptador. Si da problemas, vuelta a sldl 2.6.0 autocontenido por el mismo adaptador (Ajustes > Motor). Siempre `--no-config` y todas las opciones explícitas.
2. **Licencia**: GPL-3.0-or-later (mutagen es GPL-2.0+ y el motor es GPL/AGPL). Van incluidos el LICENSE del motor, el enlace a su código fuente exacto y los avisos de terceros.
3. **Contador de compartidos**: modo honesto. En sldl 2.x se pasa `--no-modify-share-count`. **Cambio respecto al encargo**: la ayuda de Sockseek 3.x ya no tiene esa opción; tiene `--shared-files` y `--shared-folders` (por defecto 0). Para 3.x se pasan `--shared-files 0 --shared-folders 0` explícitos. En el primer uso aparece un aviso que recomienda compartir con Nicotine+ cuando no uses Tracklister, con otra cuenta si van a la vez.
4. **Duda solo por espectro** (posible FLAC falso): el archivo se queda en la carpeta del set, con su número y una marca en el informe. A `_dudosos\` solo van las dudas de identidad: otra canción, otra versión o una duración que no cuadra.
5. **"CDJ antiguos"**: un FLAC de más de 48 kHz o de más de 24 bits se convierte a AIFF de 48 kHz/24 bits, con aviso. Por debajo se conservan el sample rate y los bits. El FLAC original se guarda en `_originales\`. Nunca se escribe AIFF-C ni 32 bits float. Conversor: soundfile + mutagen (sin ffmpeg).
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
14. **Tema por defecto, icono y logo**: el logo por defecto va sin la marca "OR". El tema por defecto y el concepto de icono los elige la rama de marca según su informe (`construccion/identidad-visual.md`), y se apuntan aquí cuando estén.
15. **Entorno**:
    - Python 3.13.2, el único instalado en el portátil;
    - PySide6-Essentials 6.12.0 en lugar del PySide6 completo, que es más pesado;
    - sin pandas ni scipy en la app.
    - Empaquetado: PyInstaller onedir sin UPX, en un zip.
16. **Motor en el zip**:
    - va el motor fijado, con su LICENSE y el enlace al código del tag exacto;
    - el workflow de GitHub Actions adjunta también el zip del código fuente al Release;
    - va yt-dlp.exe (licencia Unlicense).
17. **Modo simulado del motor real** (`--mock-files-dir`): solo se ejecutaría en este portátil si su código confirma que no abre ninguna conexión. Si no se puede confirmar, aquí solo se ejecuta `--help`/`--version`, y todas las pruebas usan el motor falso.
