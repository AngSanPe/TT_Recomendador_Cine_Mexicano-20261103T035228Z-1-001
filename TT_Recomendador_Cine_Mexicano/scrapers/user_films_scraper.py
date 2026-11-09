import sqlite3
import requests
from bs4 import BeautifulSoup
import re
import time
import random
import logging
from pathlib import Path
import argparse

# Configuración básica de los logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE = "https://letterboxd.com"

# Letterboxd protege con un reto de Cloudflare ("Just a moment...") las páginas
# /films/page/N/, el diario y las calificaciones. Solo /usuario/films/ (las 72
# películas más recientes) se sirve sin reto. No intentamos saltar el reto:
# lo detectamos y nos quedamos con lo que el sitio entrega libremente.


class RetoCloudflare(Exception):
    pass


def es_reto_cloudflare(respuesta):
    return respuesta.headers.get('cf-mitigated') == 'challenge' or (
        respuesta.status_code == 403 and 'Just a moment' in respuesta.text[:2000]
    )


def obtener_usuarios_ya_procesados(db_destino):
    """Revisa la base de datos destino para ver qué usuarios ya intentamos y no repetir trabajo."""
    if not Path(db_destino).exists():
        return set()
    conexion = sqlite3.connect(db_destino)
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT usuario FROM usuarios_procesados")
        ya_procesados = {fila[0] for fila in cursor.fetchall()}
    except sqlite3.OperationalError:
        ya_procesados = set()  # La tabla aún no existe
    conexion.close()
    return ya_procesados


def obtener_usuarios_muestra(db_path, min_peliculas, max_peliculas, limite, ya_procesados):
    """
    Extrae usuarios únicos, excluyendo a los que ya descargamos antes.
    El filtro de ya procesados se hace en Python: con miles de usuarios un
    NOT IN (?, ?, ...) rebasa el límite de parámetros de SQLite.
    """
    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()

    query = '''
        SELECT usuario
        FROM resenas
        WHERE usuario IS NOT NULL AND usuario != ''
        GROUP BY usuario
    '''
    params = []
    if max_peliculas:
        query += ' HAVING COUNT(DISTINCT pelicula_slug) BETWEEN ? AND ? '
        params.extend([min_peliculas, max_peliculas])
    else:
        query += ' HAVING COUNT(DISTINCT pelicula_slug) >= ? '
        params.append(min_peliculas)
    query += ' ORDER BY RANDOM()'

    cursor.execute(query, params)
    usuarios = [fila[0] for fila in cursor.fetchall() if fila[0] not in ya_procesados]
    conexion.close()
    return usuarios[:limite]


def inicializar_bd_historiales(db_path):
    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial_usuario (
            usuario TEXT,
            pelicula_slug TEXT,
            UNIQUE(usuario, pelicula_slug)
        )
    ''')
    # Columnas nuevas; ALTER para bases creadas con la versión anterior.
    columnas = {fila[1] for fila in cursor.execute("PRAGMA table_info(historial_usuario)")}
    if 'calificacion' not in columnas:
        cursor.execute("ALTER TABLE historial_usuario ADD COLUMN calificacion REAL")  # 0.5 a 5, NULL si no calificó
    if 'like' not in columnas:
        cursor.execute("ALTER TABLE historial_usuario ADD COLUMN \"like\" INTEGER")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios_procesados (
            usuario TEXT PRIMARY KEY,
            estado TEXT,               -- completo | parcial | vacio | error
            peliculas_guardadas INTEGER,
            peliculas_totales INTEGER, -- lo que el perfil reporta, si se pudo leer
            paginas_totales INTEGER,
            paginas_obtenidas INTEGER,
            fecha TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conexion.commit()
    conexion.close()


def guardar_historial(db_path, usuario, peliculas, resumen):
    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()
    cursor.executemany('''
        INSERT OR REPLACE INTO historial_usuario (usuario, pelicula_slug, calificacion, "like")
        VALUES (?, ?, ?, ?)
    ''', [(usuario, p['slug'], p['calificacion'], p['like']) for p in peliculas])
    cursor.execute('''
        INSERT OR REPLACE INTO usuarios_procesados
            (usuario, estado, peliculas_guardadas, peliculas_totales, paginas_totales, paginas_obtenidas)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (usuario, resumen['estado'], len(peliculas), resumen['peliculas_totales'],
          resumen['paginas_totales'], resumen['paginas_obtenidas']))
    conexion.commit()
    conexion.close()


def extraer_peliculas(soup):
    peliculas = []
    for item in soup.select('li.griditem'):
        poster = item.select_one('[data-item-slug]')
        if not poster:
            continue
        calificacion = None
        estrellas = item.select_one('.poster-viewingdata .rating')
        if estrellas:
            m = re.search(r'rated-(\d+)', ' '.join(estrellas.get('class', [])))
            if m:
                calificacion = int(m.group(1)) / 2  # rated-1..10 -> 0.5..5 estrellas
        like = 1 if item.select_one('.poster-viewingdata .like') else 0
        peliculas.append({'slug': poster['data-item-slug'], 'calificacion': calificacion, 'like': like})
    return peliculas


def extraer_totales(soup, html):
    paginas = [int(a.get_text()) for a in soup.select('.paginate-pages a, .paginate-pages span')
               if a.get_text().strip().isdigit()]
    m = re.search(r'([\d,]+)\s*(?:&nbsp;|\s)films', html)
    return (max(paginas) if paginas else 1), (int(m.group(1).replace(',', '')) if m else None)


def descargar(session, url):
    """GET con reintentos para fallas de red y 429. Lanza RetoCloudflare si aparece el reto."""
    for intento in range(1, 4):
        try:
            respuesta = session.get(url, timeout=15)
        except requests.exceptions.RequestException as e:
            logging.error(f"Error de red (posible suspensión de la Mac). Intento {intento}/3 en 10s: {e}")
            time.sleep(10)
            continue
        if es_reto_cloudflare(respuesta):
            raise RetoCloudflare(url)
        if respuesta.status_code == 429:
            logging.warning("Status 429 (demasiadas peticiones). Pausando 60 segundos...")
            time.sleep(60)
            continue
        return respuesta
    return None


def scrapear_peliculas_usuario(usuario, session, max_paginas):
    """Descarga las películas visibles del usuario: la página 1 siempre, y las
    siguientes mientras Cloudflare no las bloquee y no se rebase max_paginas."""
    todas = []
    resumen = {'estado': 'error', 'peliculas_totales': None, 'paginas_totales': None, 'paginas_obtenidas': 0}
    pagina = 1
    while True:
        # La página 1 debe pedirse sin /page/1/: esa variante sí dispara el reto.
        url = f"{BASE}/{usuario}/films/" if pagina == 1 else f"{BASE}/{usuario}/films/page/{pagina}/"
        logging.info(f"Scrapeando: {url}")
        try:
            respuesta = descargar(session, url)
        except RetoCloudflare:
            logging.warning(f"Reto de Cloudflare en la página {pagina}; se conserva lo obtenido.")
            break
        if respuesta is None:
            break
        if respuesta.status_code == 404:
            resumen['estado'] = 'vacio' if pagina == 1 else resumen['estado']
            break
        if respuesta.status_code != 200:
            logging.warning(f"Status {respuesta.status_code} en {url}")
            break

        soup = BeautifulSoup(respuesta.text, 'lxml')
        if pagina == 1:
            resumen['paginas_totales'], resumen['peliculas_totales'] = extraer_totales(soup, respuesta.text)
        peliculas = extraer_peliculas(soup)
        if not peliculas:
            break
        todas.extend(peliculas)
        resumen['paginas_obtenidas'] = pagina

        if pagina >= resumen['paginas_totales'] or pagina >= max_paginas:
            break
        pagina += 1
        time.sleep(random.uniform(2.0, 4.0))  # Pausa entre páginas

    if todas:
        resumen['estado'] = 'completo' if resumen['paginas_obtenidas'] >= (resumen['paginas_totales'] or 1) else 'parcial'
    elif resumen['estado'] != 'vacio' and resumen['paginas_obtenidas'] == 0 and resumen['paginas_totales'] == 1:
        resumen['estado'] = 'vacio'
    return todas, resumen


def main():
    parser = argparse.ArgumentParser(description="Scraper de historial de usuarios para Filtrado Colaborativo.")
    parser.add_argument('--min-mexicanas', type=int, default=3, help="Mínimo de películas mexicanas que debe tener el usuario.")
    parser.add_argument('--max-mexicanas', type=int, default=None, help="Máximo de películas mexicanas (opcional, para crear grupos cerrados).")
    parser.add_argument('--limite', type=int, default=50, help="Cantidad de usuarios a scrapear.")
    parser.add_argument('--max-paginas', type=int, default=1000,
                        help="Páginas de /films/ por usuario (72 películas c/u). Cloudscraper ahora evade la protección de Cloudflare.")
    parser.add_argument('--db-origen', type=str, default='datos/letterboxd.db', help="Ruta de la base de datos original.")
    parser.add_argument('--db-destino', type=str, help="Ruta de la base de datos a generar (ej. data/raw/historial_min3.db).")

    args = parser.parse_args()

    # Si no especifican destino, armamos uno automático
    if not args.db_destino:
        rango = f"{args.min_mexicanas}_a_{args.max_mexicanas}" if args.max_mexicanas else f"min{args.min_mexicanas}"
        args.db_destino = f"data/raw/historial_{rango}.db"

    Path(args.db_destino).parent.mkdir(parents=True, exist_ok=True)
    inicializar_bd_historiales(args.db_destino)

    ya_procesados = obtener_usuarios_ya_procesados(args.db_destino)

    logging.info(f"Iniciando extracción. Rango: {args.min_mexicanas} a {args.max_mexicanas if args.max_mexicanas else 'Infinito'}")
    logging.info(f"Se buscarán {args.limite} usuarios nuevos y se guardarán en {args.db_destino}")
    logging.info(f"Usuarios previamente procesados e ignorados en esta sesión: {len(ya_procesados)}")

    usuarios = obtener_usuarios_muestra(args.db_origen, args.min_mexicanas, args.max_mexicanas, args.limite, ya_procesados)
    logging.info(f"Se obtuvieron {len(usuarios)} usuarios aleatorios para procesar.")

    import cloudscraper
    session = cloudscraper.create_scraper()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,es;q=0.8'
    })

    for indice, usuario in enumerate(usuarios, 1):
        logging.info(f"--- [Min:{args.min_mexicanas}] Procesando usuario {indice}/{len(usuarios)}: {usuario} ---")
        peliculas, resumen = scrapear_peliculas_usuario(usuario, session, args.max_paginas)
        if resumen['estado'] == 'error':
            # No se marca como procesado: se reintentará en la siguiente corrida.
            logging.error(f"No se pudo descargar a {usuario}; se reintentará en otra corrida.")
        else:
            guardar_historial(args.db_destino, usuario, peliculas, resumen)
            logging.info(f"{usuario}: {len(peliculas)} películas guardadas "
                         f"(perfil reporta {resumen['peliculas_totales']}, estado {resumen['estado']}).")

        time.sleep(random.uniform(3.0, 6.0))  # Pausa entre usuarios

    logging.info("¡Proceso finalizado con éxito!")


if __name__ == "__main__":
    main()
