import os
import re
import time
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

SPREADSHEET_ID = "1f_Pd8XKsPFnNurWVoD0HR9Lk0mT1fbXBC58joBPJRrE"
CREDENTIALS_FILE = "credentials.json"

TAB_CLIENTES = "Clientes"
TAB_ENVIADAS = "Propiedades Enviadas"
TAB_SUGERENCIAS = "SUGERENCIAS DIARIAS"

MAX_PROPIEDADES_POR_CLIENTE = 5
DOMINIO_BUSQUEDA = "https://www.remax.com.ar"
DOMINIO_AGENTE = "https://davidhilu.remax.com.ar"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def normalizar_link_agente(url_raw: str) -> str:
    clean = str(url_raw or "").strip().split("?")[0].rstrip("/")
    slug = extraer_slug_propiedad(clean)
    return f"{DOMINIO_AGENTE}/listings/{slug}" if slug else clean

def extraer_slug_propiedad(url: str) -> str:
    clean = str(url or "").strip().split("?")[0].rstrip("/").lower()
    return clean.split("/")[-1] if clean else ""

def parsear_presupuesto(valor_raw: str) -> int:
    digitos = re.sub(r"[^0-9]", "", str(valor_raw or ""))
    return int(digitos) if digitos else 0

def parsear_ambientes(amb_raw: str) -> int:
    if not amb_raw or str(amb_raw).strip() == "-":
        return 0
    m = re.search(r"(\d+)", str(amb_raw))
    return int(m.group(1)) if m else 0

def mapear_operacion_url(op_raw: str) -> str:
    op = str(op_raw or "").lower()
    if "temporario" in op:
        return "alquiler-temporario"
    if "alquiler" in op:
        return "alquiler"
    return "venta"

def mapear_tipo_propiedad_url(tp_raw: str) -> str:
    tp = str(tp_raw or "").lower()
    if "ph" in tp:
        return "ph"
    if "casa" in tp:
        return "casa"
    if "local" in tp:
        return "local"
    if "oficina" in tp:
        return "oficina"
    if "terreno" in tp or "lote" in tp:
        return "terreno"
    return "departamento"

def iniciar_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=es-AR")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    if os.path.exists("/usr/bin/chromium-browser"):
        opts.binary_location = "/usr/bin/chromium-browser"
    elif os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"

    if os.path.exists("/usr/bin/chromedriver"):
        return webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=opts)
    return webdriver.Chrome(options=opts)

def construir_urls_busqueda(cliente: dict) -> list:
    op_slug = mapear_operacion_url(cliente["operacion"])
    tp_slug = mapear_tipo_propiedad_url(cliente["tipo_propiedad"])
    zonas = [z.strip() for z in str(cliente["zonas"]).split(",") if z.strip() and z.strip() != "-"]
    if not zonas:
        zonas = ["capital-federal"]

    urls = []
    for zona in zonas:
        z_slug = re.sub(r"[^a-z0-9]+", "-", zona.lower()).strip("-")
        if z_slug in ("caba", "capital", "capital-federal"):
            z_slug = "capital-federal"
        base = f"{DOMINIO_BUSQUEDA}/listings/{op_slug}-{tp_slug}-en-{z_slug}"
        params = []
        if cliente["presupuesto_num"] > 0:
            params.append(f"priceTo={cliente['presupuesto_num']}")
        if cliente["ambientes_num"] > 0:
            params.append(f"roomsFrom={cliente['ambientes_num']}&roomsTo={cliente['ambientes_num'] + 1}")
        params.append("sort=-createdAt")
        urls.append((zona, f"{base}?{'&'.join(params)}"))
    return urls

def buscar_propiedades_cliente(driver, cliente: dict, historial_slugs: set) -> list:
    resultados = []
    for zona_label, search_url in construir_urls_busqueda(cliente):
        if len(resultados) >= MAX_PROPIEDADES_POR_CLIENTE:
            break
        logging.info(f"Consultando [{cliente['nombre']}]: {search_url}")
        try:
            driver.get(search_url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/listings/']"))
            )
            time.sleep(3)
        except Exception as e:
            logging.warning(f"Sin resultados cargados en {search_url}: {e}")
            continue

        soup = BeautifulSoup(driver.page_source, "html.parser")
        vistos = set()
        for a in soup.select("a[href*='/listings/']"):
            if len(resultados) >= MAX_PROPIEDADES_POR_CLIENTE:
                break
            href = a.get("href", "")
            if "-en-" in href:
                continue

            link_agente = normalizar_link_agente(href)
            slug = extraer_slug_propiedad(link_agente)
            if not slug or len(slug) < 10 or slug in historial_slugs or slug in vistos:
                continue

            card = a.find_parent(["article", "div"])
            texto_card = card.get_text(" | ", strip=True) if card else a.get_text(" ", strip=True)
            precio_match = re.search(r"(USD|U\$S|\$)\s*[\d\.\,]+", texto_card, re.IGNORECASE)
            precio_str = precio_match.group(0).strip() if precio_match else "Consultar"

            precio_num = parsear_presupuesto(precio_str)
            if cliente["presupuesto_num"] > 0 and precio_num > 0:
                if precio_num > int(cliente["presupuesto_num"] * 1.05):
                    continue

            titulo_tag = card.find(["h2", "h3", "h4"]) if card else None
            titulo = titulo_tag.get_text(" ", strip=True) if titulo_tag else slug.replace("-", " ").upper()
            titulo = re.sub(r"\s+", " ", titulo)[:140]

            vistos.add(slug)
            historial_slugs.add(slug)
            resultados.append([
                datetime.now().strftime("%d/%m/%Y"),
                cliente["nombre"],
                f"{cliente['operacion'].upper()} / {zona_label.upper()}",
                titulo,
                precio_str,
                link_agente,
                "PENDIENTE"
            ])
    return resultados

def ejecutar_busqueda_diaria():
    sh = conectar_sheets()
    ws_clientes = sh.worksheet(TAB_CLIENTES)
    ws_enviadas = sh.worksheet(TAB_ENVIADAS)
    ws_sugerencias = sh.worksheet(TAB_SUGERENCIAS)

    clientes_activos = []
    for row in ws_clientes.get_all_values()[3:]:
        if len(row) < 20:
            continue
        id_cli = row[0].strip()
        nombre = row[2].strip() or row[1].strip()
        if id_cli and nombre and row[19].strip().upper() == "ACTIVA":
            clientes_activos.append({
                "nombre": nombre,
                "operacion": row[5].strip() or "Compra",
                "tipo_propiedad": row[6].strip() or "DEPARTAMENTO",
                "ambientes_num": parsear_ambientes(row[7]),
                "zonas": row[8].strip() or "CABA",
                "presupuesto_num": parsear_presupuesto(row[9])
            })

    if not clientes_activos:
        logging.info("No hay clientes activos.")
        return

    historial = {c["nombre"].upper(): set() for c in clientes_activos}
    for row in ws_enviadas.get_all_values()[3:]:
        if len(row) >= 3 and row[1].strip().upper() in historial:
            historial[row[1].strip().upper()].add(extraer_slug_propiedad(row[2]))
    for row in ws_sugerencias.get_all_values()[3:]:
        if len(row) >= 6 and row[1].strip().upper() in historial:
            historial[row[1].strip().upper()].add(extraer_slug_propiedad(row[5]))

    driver = iniciar_driver()
    nuevas_filas = []
    try:
        for cli in clientes_activos:
            encontradas = buscar_propiedades_cliente(driver, cli, historial[cli["nombre"].upper()])
            logging.info(f"{cli['nombre']}: {len(encontradas)} propiedades nuevas.")
            nuevas_filas.extend(encontradas)
    finally:
        driver.quit()

    if nuevas_filas:
        ws_sugerencias.append_rows(nuevas_filas, value_input_option="USER_ENTERED")
        logging.info(f"Total filas nuevas agregadas: {len(nuevas_filas)}")

if __name__ == "__main__":
    ejecutar_busqueda_diaria()
