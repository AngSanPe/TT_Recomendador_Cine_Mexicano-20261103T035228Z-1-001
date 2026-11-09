# Scraper de reseñas de cine mexicano en Letterboxd

Recolecta las opiniones escritas que los usuarios de Letterboxd publican sobre
películas mexicanas y las guarda en una base SQLite lista para analizar
(exportable a CSV y JSONL).

La lista semilla [peliculas_mexicanas.txt](peliculas_mexicanas.txt) trae **4,164
películas**: 56 curadas y verificadas a mano, más la cola larga tomada de listas
públicas de Letterboxd. No necesitas API key para empezar.

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Cuánto se puede recolectar (medido, no estimado)

Letterboxd **corta el listado de reseñas en la página 256**: la 257 llega vacía.
Son **3,072 reseñas como máximo por película**, tenga las que tenga. *Y tu mamá
también* tiene 172,628 reseñas escritas y solo 3,072 son accesibles.

| | |
|---|---|
| Reseñas en las 56 películas más conocidas | 750,178 |
| Alcanzables con el tope de paginación | 124,104 (16.5%) |
| De esas 56, cuántas ya topan el límite | 33 |
| Películas en la lista semilla | 4,164 |
| Techo estimado para **todo** el cine mexicano | 200,000 – 400,000 reseñas |

Para juntar 10 millones harían falta 3,255 películas topando sus 3,072 reseñas
cada una, y no existen tantas películas mexicanas con ese volumen de público.
Si necesitas más filas que eso, las alternativas son ampliar el alcance
(cine latinoamericano o en español) o sumar otras fuentes.

## Uso rápido

```bash
# Lista semilla incluida: 4,164 películas (56 curadas + cola larga de listas públicas)
.venv/bin/python -m letterboxd_scraper recolectar --paginas 5

# Una o varias películas concretas
.venv/bin/python -m letterboxd_scraper recolectar --slug roma-2018 --slug huesera

# Revisar y exportar (solo reseñas en español)
.venv/bin/python -m letterboxd_scraper resumen
.venv/bin/python -m letterboxd_scraper exportar --csv datos/resenas.csv --idioma es
```

### Ampliar el corpus sin API key: listas públicas

La comunidad de Letterboxd mantiene listas enormes de cine mexicano, y sus
slugs vienen del propio sitio, así que son válidos por construcción — no hay
que adivinarlos ni verificarlos uno por uno. Son 100 películas por página.

```bash
.venv/bin/python -m letterboxd_scraper recolectar \
    --lista https://letterboxd.com/mayitzin/list/mexico/ \
    --solo-mexicanas --paginas 256 --retardo 5
```

Ojo con qué contienen: esas listas suelen mezclar cine *sobre* México con cine
*de* México (*The Treasure of the Sierra Madre*, por ejemplo). Por eso existe
`--solo-mexicanas`, que descarta las películas donde Letterboxd no menciona a
México entre los países. Es un filtro imperfecto —Letterboxd registra *Roma*
como UK/USA— así que la película se guarda de todos modos en la tabla
`peliculas` con su campo `paises`: puedes rehacer el filtro en SQL más tarde
sin volver a descargar nada.

Listas útiles verificadas:

| Lista | Títulos |
|---|---|
| [mayitzin/list/mexico](https://letterboxd.com/mayitzin/list/mexico/) | 3,751 |
| [annabetth/list/mexico-in-films](https://letterboxd.com/annabetth/list/mexico-in-films/) | 1,252 |
| [monstervision/list/highest-rated-mexican-movies](https://letterboxd.com/monstervision/list/highest-rated-mexican-movies-mejores-peliculas/) | 247 |

### Recolección masiva: todo el cine mexicano

Son tres pasos, cada uno reanudable. La división existe porque resolver el slug
de Letterboxd cuesta una petición por película: se hace una sola vez y queda
guardado en la tabla `catalogo`.

Primero la credencial, **una sola vez**. Pégala en el archivo `.env` (ya está
en `.gitignore`, no se sube a ningún repositorio) y verifícala:

```bash
echo 'TMDB_API_KEY=tu_clave_aqui' > .env
.venv/bin/python tmdb.py        # confirma que sirve y cuántas películas MX ve
```

Sirven tanto la *API Key (v3)* como el *Read Access Token (v4)*; el scraper
detecta cuál es por su forma.

```bash
# 1. Catálogo: todas las películas de origen MX en TMDb, año por año.
#    Solo habla con TMDb, no con Letterboxd. Tarda minutos.
.venv/bin/python -m letterboxd_scraper catalogo --desde-anio 1930

#    ¿Solo producción 100% mexicana, sin coproducciones? Agrega --estricto.
#    Cuesta una petición extra por título y descarta cosas como Roma (MX/USA).
.venv/bin/python -m letterboxd_scraper catalogo --desde-anio 1930 --estricto

# 2. Depurar: TMDb marca como "de origen MX" cosas que no lo son (The Faculty,
#    PAW Patrol). Este paso consulta la ficha de cada una y guarda sus países
#    de producción reales. Solo habla con TMDb.
#      --modo con-mx  (predeterminado) conserva coproducciones: Roma, Pan's Labyrinth
#      --modo solo-mx deja únicamente producción 100% mexicana
.venv/bin/python -m letterboxd_scraper depurar --min-votos 5

# 3. Resolver: tmdb_id -> slug de Letterboxd. Una petición por película.
#    --min-votos descarta las que no tienen público (y por tanto no tendrán reseñas).
.venv/bin/python -m letterboxd_scraper resolver --min-votos 5 --retardo 5

# 4. Recolectar, de las más votadas a las menos. Corre el tiempo que aguantes:
#    al reanudar sigue donde se quedó.
.venv/bin/python -m letterboxd_scraper recolectar --del-catalogo --paginas 256 --retardo 5
```

Cálculo de tiempo: a 5 s por petición son ~700 páginas por hora, es decir unas
**8,400 reseñas por hora**. Llegar a 300 mil reseñas son ~36 horas de trabajo
repartidas en varias sesiones.

**Sobre el ritmo:** Letterboxd está detrás de Cloudflare y empieza a devolver
403 si lo presionas (me pasó tras un par de cientos de peticiones seguidas). El
cliente lo detecta, hace espera exponencial y sigue sin romperse, pero para
corridas largas usa `--retardo 5` o más. Ir más rápido no te da más datos: te
da bloqueos.

Cada página de reseñas trae 12 opiniones, así que `--paginas 5` son ~60 reseñas
por película. La recolección es **reanudable**: las reseñas se insertan con
`INSERT OR IGNORE` sobre su identificador de Letterboxd, y el HTML descargado
queda en `datos/cache/`, así que volver a correr el comando no repite trabajo.

### Sinopsis de las películas recolectadas

```bash
.venv/bin/python -m letterboxd_scraper sinopsis
```

Guarda en la tabla `peliculas` la sinopsis de cada película ya registrada y la
exporta a `datos/sinopsis_peliculas.csv`. El español viene de TMDb (es-MX y, si
no hay, es-ES); el inglés viene de la ficha de Letterboxd, que ya está en
`datos/cache/`, así que no cuesta peticiones al sitio. Es reanudable: solo
consulta las que no se han revisado (`--todas` para rehacerlas).

### Sinopsis de un catálogo de IMDb (`imdb_movies.csv`)

```bash
nohup caffeinate -i .venv/bin/python -m letterboxd_scraper sinopsis-imdb \
    > datos/sinopsis_imdb.log 2>&1 &
tail -f datos/sinopsis_imdb.log        # avance, ritmo y tiempo restante
```

TMDb acepta el `tconst` de IMDb directamente, así que es **una petición por
película**, sin buscar por título. Va de la más votada en IMDb a la menos, a
~40 por segundo: las 757,649 películas tardan unas 5 h 20 min. Es reanudable
(lo consultado queda en `datos/sinopsis_imdb.db`) y se detiene con
`kill <pid>` o Ctrl+C sin perder lo guardado. `caffeinate` evita que la Mac
se duerma mientras corre.

Al terminar escribe `datos/sinopsis_imdb.csv`: una fila por película, en el
orden del CSV original, con `sinopsis_es` (es-MX → es-ES → otro español),
`sinopsis_en` (en-US → en-GB) y, si no hay ninguna de las dos,
`sinopsis_otra` en el idioma original. La columna `estado` dice qué pasó:
`con_sinopsis`, `sin_sinopsis` (TMDb la tiene sin texto), `no_en_tmdb` o
`pendiente` (aún no consultada).

```bash
# Regenerar el CSV a mitad de la corrida, con lo que ya haya
.venv/bin/python -m letterboxd_scraper sinopsis-imdb --solo-exportar
# Solo las filas que sí tienen sinopsis
.venv/bin/python -m letterboxd_scraper sinopsis-imdb --solo-exportar --solo-con-sinopsis
```

## Qué se guarda

Tabla `peliculas`: `slug`, `titulo`, `anio`, `directores`, `paises`, `tmdb_id`,
`calificacion_promedio`, `url`, y tras el comando `sinopsis`: `titulo_es`,
`sinopsis_es`, `sinopsis_es_fuente` (`tmdb es-MX`, `tmdb es-ES`…), `sinopsis_en`,
`sinopsis_en_fuente` (`letterboxd` o `tmdb en-US`).

Tabla `catalogo` (descubrimiento de TMDb): `tmdb_id`, `titulo`, `anio`,
`popularidad`, `votos`, `paises`, `slug`, `estado` (`pendiente` → `resuelto` →
`recolectado`; `descartada` si no es mexicana, `sin_ficha` si no existe en
Letterboxd). Nada se borra: lo descartado queda con sus países para que puedas
revisar o cambiar el criterio sin volver a consultar TMDb.

Las películas sin `production_countries` en TMDb se marcan con `paises = '?'` y
**se conservan**. Son 168 en el catálogo actual, casi todas cine reciente y
pequeño; descartarlas sería perderlas por un hueco de metadatos, no por su
origen, dado que la consulta que las trajo ya filtraba por país de origen MX.

Tabla `resenas`: `id`, `pelicula_slug`, `usuario`, `nombre_visible`, `url`,
`calificacion` (0.5 a 5.0), `fecha`, `texto`, `likes`, `spoiler`, `idioma`,
`es_relectura`, `recolectado_en`.

El campo `idioma` es el que declara Letterboxd para la reseña; sirve para
quedarte solo con las opiniones en español:

```sql
SELECT texto, calificacion FROM resenas WHERE idioma = 'es';
```

## Decisiones de diseño

**Se respeta el `robots.txt` de Letterboxd.** El sitio prohíbe explícitamente
`/*/country/*` (listados por país), `/*/by/*` (órdenes alternativos),
`/*/genre/*`, `/*/decade/*` y `/films/year/*`. Por eso:

- El descubrimiento de películas mexicanas **no** se hace con
  `letterboxd.com/films/country/mexico/`, sino con la API oficial de TMDb
  (`with_origin_country=MX`) resolviendo cada ficha vía `letterboxd.com/tmdb/<id>/`,
  o con la lista semilla incluida.
- Las reseñas se leen de `/film/<slug>/reviews/page/N/`, que sí está permitido,
  y no de `/reviews/by/activity/`. Eso significa que el orden es el que da el
  sitio por omisión (actividad reciente), no "las más populares".

Pista sin confirmar: `/film/<slug>/reviews/rated/<n>/` es un listado aparte por
calificación, y en teoría cada uno tendría su propia ventana de 256 páginas
(hasta ~30 mil reseñas por película en vez de 3,072). La primera página
responde, pero al paginarla obtuve 403 incluso a 4 s de intervalo. Si hace falta
más volumen, vale la pena reintentarlo con calma.

El módulo [robots.py](letterboxd_scraper/robots.py) implementa el chequeo a mano
porque `urllib.robotparser` no interpreta los comodines `*` de estos patrones y,
además, recibe un 403 al pedir el archivo con su propio User-Agent.

**Ritmo cortés.** Una petición a la vez, 2.5 s de pausa con jitter, reintentos
con espera exponencial ante 403/429/5xx (el 403 de Letterboxd suele ser el reto
de Cloudflare: la respuesta correcta es ir más lento, no insistir). El endpoint
`/s/full-text/` está detrás de Cloudflare y no se usa; el texto que se guarda es
el que aparece en el listado.

## Consideraciones para el trabajo terminal

- Las reseñas son texto público, pero incluyen nombres de usuario. Para
  publicar resultados conviene seudonimizar `usuario` y `nombre_visible`, o
  reportar solo agregados.
- Letterboxd tiene términos de uso y una API oficial en beta
  (<https://letterboxd.com/api-beta/>); si el proyecto crece o se publica,
  vale la pena solicitar acceso.
- Los países que reporta Letterboxd no siempre coinciden con TMDb (por ejemplo,
  *Roma* aparece como UK/USA). Si el criterio de "película mexicana" es central
  para tu análisis, documenta cuál fuente usas y guárdala en la columna `paises`.
