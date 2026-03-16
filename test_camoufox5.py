import sys
import asyncio
import json
import re
from datetime import datetime
import os
import platform
import shutil
import pytesseract
from PIL import Image
from playwright.async_api import async_playwright

# ── Configuración de Tesseract ──
# Detectar sistema operativo y configurar Tesseract automáticamente
if platform.system() == "Windows":
    # En Windows, buscar en la ruta típica
    TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
else:
    # En Linux/Docker, Tesseract está en el PATH por defecto
    tesseract_cmd = shutil.which("tesseract")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        print(f"✅ Tesseract encontrado en: {tesseract_cmd}")
    else:
        print("⚠️  Tesseract no encontrado en PATH")

# ── Parámetros desde línea de comandos ──
# Uso: python scraper.py TACNA Z3I040
if len(sys.argv) >= 3:
    CIUDAD = sys.argv[1].upper()
    PLACA  = sys.argv[2].upper()
else:
    # Valores por defecto si no se pasan argumentos
    CIUDAD = "CHIMBOTE"
    PLACA  = "H1M467"

# ── Credenciales (pueden ser sobrescritas por parámetros) ──
USUARIO = "STEVE70835372"
PASSWORD = "ELVIS123"

def analizar_asiento_con_ocr(carpeta: str) -> dict:
    """Extrae texto de las imágenes del asiento usando Tesseract OCR (función síncrona)"""
    print(f"  📖 Extrayendo texto con OCR: {carpeta}...")

    # ── Cargar imágenes de la carpeta ──
    archivos_img = sorted([
        os.path.join(carpeta, f) for f in os.listdir(carpeta)
        if f.endswith(".png")
    ])
    
    if not archivos_img:
        print(f"  ⚠️  No hay imágenes en {carpeta}")
        return {"texto_completo": ""}

    # ── Extraer texto de cada imagen ──
    texto_total = ""
    
    for i, ruta_imagen in enumerate(archivos_img):
        try:
            print(f"  📄 Procesando {os.path.basename(ruta_imagen)} ({i+1}/{len(archivos_img)})...")
            img = Image.open(ruta_imagen)
            texto = pytesseract.image_to_string(img, lang="spa")
            texto_total += f"\n\n--- Página {i+1} ({os.path.basename(ruta_imagen)}) ---\n"
            texto_total += texto
        except Exception as e:
            print(f"  ⚠️  Error procesando {ruta_imagen}: {e}")

    print(f"  ✅ OCR extrajo texto de {len(archivos_img)} imagen(es)")
    return {"texto_completo": texto_total.strip()}


# ═══════════════════════════════════════════
# HELPER: procesar UN card en siguelo
# ═══════════════════════════════════════════
async def procesar_card_siguelo(browser, card, ciudad, indice):
    """Abre una nueva página y procesa un card individual"""
    page = None
    carpeta = None
    
    try:
        page = await browser.new_page()
        anio  = re.search(r'\d{4}', card["titulo"]).group()
        nro   = card["titulo"].split("-")[-1].strip().lstrip("0") or "0"
        print(f"  [{indice+1}] 🔍 {card['acto']} | Año:{anio} Nro:{nro}")
        acto_limpio = card["acto"].replace(" ", "_").replace("/", "-")[:20]
        nombre_carpeta = f"{anio}_{nro.zfill(8)}_{acto_limpio}"

        # ── Intentar cargar URL con reintentos ──
        url_siguelo = "https://siguelo.sunarp.gob.pe/siguelo/"
        max_retries_url = 3
        url_loaded = False
        
        for attempt in range(max_retries_url):
            try:
                print(f"  [{indice+1}] 🌐 Intento {attempt + 1}/{max_retries_url}: Cargando {url_siguelo}...")
                await page.goto(
                    url_siguelo,
                    wait_until="domcontentloaded",  # Cambiado a domcontentloaded para ser más tolerante
                    timeout=90000  # 90 segundos
                )
                url_loaded = True
                print(f"  [{indice+1}] ✅ URL cargada exitosamente")
                break
            except Exception as url_error:
                if attempt == max_retries_url - 1:
                    error_msg = f"No se pudo cargar la URL después de {max_retries_url} intentos: {str(url_error)}"
                    print(f"  [{indice+1}] ❌ {error_msg}")
                    raise Exception(error_msg)
                print(f"  [{indice+1}] ⚠️  Intento {attempt + 1} fallido, reintentando en 3 segundos...")
                await asyncio.sleep(3)
        
        if not url_loaded:
            raise Exception("No se pudo cargar la URL después de todos los intentos")
        
        # ── Continuar con el procesamiento ──
        try:
            await esperar_cloudflare(page)
        except Exception as e:
            print(f"  [{indice+1}] ⚠️  Advertencia en Cloudflare: {e}")
            # Continuar aunque falle Cloudflare
        
        try:
            await clic_acepto(page)
        except Exception as e:
            print(f"  [{indice+1}] ⚠️  Advertencia en clic Acepto: {e}")
            # Continuar aunque falle
        
        try:
            await seleccionar_oficina(page, oficina=ciudad)
        except Exception as e:
            raise Exception(f"Error al seleccionar oficina: {str(e)}")
        
        try:
            await seleccionar_anio(page, anio=anio)
        except Exception as e:
            raise Exception(f"Error al seleccionar año: {str(e)}")
        
        try:
            await escribir_numero_titulo(page, numero=nro)
        except Exception as e:
            raise Exception(f"Error al escribir número de título: {str(e)}")
        
        try:
            await hacer_clic_turnstile(page)
            await esperar_turnstile_resuelto(page)
        except Exception as e:
            print(f"  [{indice+1}] ⚠️  Advertencia en Turnstile: {e}")
            # Continuar aunque falle Turnstile
        
        try:
            await clic_buscar_siguelo(page)
        except Exception as e:
            raise Exception(f"Error al hacer clic en buscar: {str(e)}")
        
        try:
            await clic_acceder_asiento(page)
        except Exception as e:
            raise Exception(f"Error al acceder al asiento: {str(e)}")

        # ── Descargar imágenes ──
        try:
            carpeta, archivos = await descargar_pdf_como_screenshots(page, nombre_carpeta=nombre_carpeta)
            print(f"  [{indice+1}] ✅ Imágenes guardadas en: {carpeta}/")
        except Exception as e:
            raise Exception(f"Error al descargar imágenes: {str(e)}")
        
        # ── Analizar inmediatamente con OCR ──
        print(f"  [{indice+1}] 📖 Extrayendo texto con OCR...")
        
        try:
            # Ejecutar OCR en un thread para no bloquear (Tesseract es síncrono)
            import concurrent.futures
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                analisis_ocr = await loop.run_in_executor(
                    executor, 
                    analizar_asiento_con_ocr,
                    carpeta
                )
            
            print(f"  [{indice+1}] ✅ Extracción OCR completada")
        except Exception as e:
            print(f"  [{indice+1}] ⚠️  Error en OCR: {e}")
            analisis_ocr = {"texto_completo": ""}
        
        return {
            "card": card,
            "analisis_ia": analisis_ocr,
            "carpeta_creada": carpeta  # Rastrear carpeta creada para limpieza
        }

    except Exception as e:
        error_msg = str(e)
        print(f"  [{indice+1}] ❌ Error procesando card: {error_msg}")
        
        # Limpiar carpeta si se creó pero hubo error
        if carpeta and os.path.exists(carpeta):
            try:
                import shutil
                shutil.rmtree(carpeta)
                print(f"  [{indice+1}] 🗑️  Carpeta temporal eliminada: {carpeta}")
            except Exception as cleanup_error:
                print(f"  [{indice+1}] ⚠️  No se pudo limpiar carpeta: {cleanup_error}")
        
        return {
            "card": card,
            "error": error_msg,
            "analisis_ia": None
        }
    finally:
        if page:
            try:
                await page.close()
            except Exception as e:
                print(f"  [{indice+1}] ⚠️  Error al cerrar página: {e}")


# ═══════════════════════════════════════════
# OPCIÓN 1: SECUENCIAL
# ═══════════════════════════════════════════
async def procesar_secuencial(browser, datos, ciudad):
    print("\n🐢 MODO SECUENCIAL — uno por uno")
    resultados = []
    for i, card in enumerate(datos):
        print(f"\n── Card {i+1}/{len(datos)} ──")
        resultado = await procesar_card_siguelo(browser, card, ciudad, i)
        resultados.append(resultado)
        
        # ── Pausa calmada entre cards ──
        if i < len(datos) - 1:  # No esperar después del último
            print(f"  ⏸️  Pausa de 3 segundos antes del siguiente...")
            await asyncio.sleep(3)
    
    return resultados



async def esperar_cloudflare(page):
    for _ in range(60):
        content = await page.content()
        if "Just a moment" not in content and "cf-browser-verification" not in content:
            print("✅ Cloudflare superado")
            return
        await page.wait_for_timeout(1000)
    print("⚠️  Tiempo agotado esperando Cloudflare")

async def hacer_clic_turnstile(page):
    """Hace clic en el checkbox del Turnstile de Cloudflare"""
    print("🔲 Buscando Turnstile...")

    for _ in range(30):
        try:
            # Buscar el iframe del turnstile por su URL
            turnstile_frame = None
            for frame in page.frames:
                if "challenges.cloudflare.com" in frame.url:
                    turnstile_frame = frame
                    break

            if turnstile_frame:
                # Clic en el checkbox dentro del iframe
                checkbox = await turnstile_frame.wait_for_selector(
                    "input[type='checkbox'], .ctp-checkbox-label, body",
                    timeout=3000
                )
                if checkbox:
                    await checkbox.click()
                    print("✅ Clic en Turnstile realizado")
                    await page.wait_for_timeout(3000)
                    return

        except Exception:
            pass

        await page.wait_for_timeout(1000)

    # Si no funcionó con el frame, intentar por posición del iframe
    print("⚠️  Intentando clic por posición del iframe...")
    try:
        iframe_element = await page.wait_for_selector(
            "iframe[src*='challenges.cloudflare.com']",
            timeout=10000
        )
        if iframe_element:
            box = await iframe_element.bounding_box()
            if box:
                # Clic en el centro-izquierda donde está el checkbox
                await page.mouse.click(
                    box["x"] + 25,       # posición X del checkbox
                    box["y"] + box["height"] / 2  # centro vertical
                )
                print("✅ Clic por coordenadas realizado")
                await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"❌ No se pudo hacer clic en Turnstile: {e}")
        print("👆 Por favor haz clic manualmente en el checkbox")
        await page.wait_for_timeout(15000)

async def esperar_turnstile_resuelto(page):
    """Espera a que el token del Turnstile tenga valor (significa que fue resuelto)"""
    print("⏳ Esperando que Turnstile se resuelva...")
    for _ in range(60):
        try:
            token = await page.eval_on_selector(
                "input[name='cf-turnstile-response']",
                "el => el.value"
            )
            if token and len(token) > 10:
                print("✅ Turnstile resuelto, token obtenido")
                return True
        except Exception:
            pass
        await page.wait_for_timeout(1000)
    print("⚠️  Turnstile no se resolvió en tiempo esperado")
    return False

async def seleccionar_dropdown_nz(page, index, texto_buscar):
    """
    Selecciona una opción en un dropdown de Angular (nz-select)
    index: posición del dropdown (0 = primero, 1 = segundo, etc.)
    texto_buscar: texto a buscar/seleccionar
    """
    print(f"🔽 Abriendo dropdown #{index + 1}...")

    # Obtener todos los selectores nz-select
    selectores = await page.query_selector_all("nz-select-top-control")
    if index >= len(selectores):
        print(f"❌ No se encontró dropdown #{index + 1}")
        return

    # Clic para abrir el dropdown
    await selectores[index].click()
    await page.wait_for_timeout(800)

    # Escribir en el campo de búsqueda del dropdown
    inputs = await page.query_selector_all("nz-select-search input")
    if index < len(inputs):
        await inputs[index].fill(texto_buscar)
        await page.wait_for_timeout(600)

    # Esperar que aparezcan las opciones
    await page.wait_for_selector("nz-option-item", timeout=10000)

    # Seleccionar la opción que coincida con el texto
    opciones = await page.query_selector_all("nz-option-item")
    for opcion in opciones:
        texto = await opcion.inner_text()
        if texto_buscar.upper() in texto.upper():
            await opcion.click()
            print(f"  ✅ Seleccionado: {texto.strip()}")
            await page.wait_for_timeout(800)
            return

    print(f"  ⚠️  No se encontró la opción '{texto_buscar}'")

async def esperar_y_resolver_turnstile_busqueda(page):
    """Espera el Turnstile que aparece después de buscar y lo resuelve"""
    print("⏳ Esperando Turnstile post-búsqueda...")
    await page.wait_for_timeout(2000)
    await hacer_clic_turnstile(page)
    await esperar_turnstile_resuelto(page)

async def clic_boton_detalle_tabla(page):
    """Hace clic en el botón de lupa dentro de la tabla de resultados"""
    print("🔍 Buscando botón de detalle en tabla...")
    await page.wait_for_selector(
        "app-button#tabla button.centradoOpciones",
        timeout=15000
    )
    # Si hay varios resultados, clic en el primero
    botones = await page.query_selector_all("app-button#tabla button.centradoOpciones")
    if botones:
        await botones[0].click()
        print(f"✅ Clic en botón detalle (fila 1 de {len(botones)} resultados)")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
    else:
        print("❌ No se encontraron botones de detalle en la tabla")

async def escribir_numero_busqueda(page, numero):
    """Escribe el número en el input de búsqueda"""
    print(f"✍️  Escribiendo número: {numero}...")
    await page.wait_for_selector("input#numero", timeout=15000)
    await page.fill("input#numero", str(numero))
    await page.wait_for_timeout(600)
    print("✅ Número ingresado")

async def clic_buscar(page):
    """Hace clic en el botón Buscar"""
    print("🔍 Haciendo clic en Buscar...")
    try:
        await page.wait_for_selector(
            "button.ant-btn-primary span.anticon-search",
            timeout=10000
        )
        await page.click("button.ant-btn-primary span.anticon-search")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        print("✅ Búsqueda ejecutada")
    except Exception as e:
        error_msg = f"Error al hacer clic en botón Buscar: {str(e)}"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)

async def extraer_datos_drawer(page):
    """Extrae toda la información de los cards del drawer/panel lateral"""
    print("📊 Extrayendo datos del drawer...")
    
    # Esperar que cargue el drawer
    await page.wait_for_selector("div.ant-drawer-body", timeout=15000)
    await page.wait_for_timeout(1500)

    resultados = []

    # Extraer info del encabezado (Partida y Nro páginas)
    encabezado = {}
    try:
        filas_header = await page.query_selector_all(
            "div.ant-drawer-body thead .ant-table-row"
        )
        for fila in filas_header:
            texto = (await fila.inner_text()).strip()
            if "Partida:" in texto:
                encabezado["partida"] = texto.replace("Partida:", "").strip()
            elif "Nro paginas:" in texto:
                encabezado["nro_paginas"] = texto.replace("Nro paginas:", "").strip()
    except Exception as e:
        print(f"  ⚠️  Error leyendo encabezado: {e}")

    print(f"  📋 Partida: {encabezado.get('partida', 'N/A')}")
    print(f"  📋 Nro Páginas: {encabezado.get('nro_paginas', 'N/A')}")

    # Extraer cada card (fila tbody)
    filas = await page.query_selector_all(
        "div.ant-drawer-body tbody.ant-table-tbody tr.ant-table-row"
    )
    print(f"  📦 Cards encontrados: {len(filas)}")

    for i, fila in enumerate(filas):
        card = {}

        try:
            # Título
            titulo_el = await fila.query_selector("div.bg-gray:first-child")
            if titulo_el:
                card["titulo"] = (await titulo_el.inner_text()).strip()

            # Todos los div.bg-gray y bg-white
            divs = await fila.query_selector_all("div.bg-gray, div.bg-white")
            for div in divs:
                texto = (await div.inner_text()).strip()

                if "Nro. Asiento:" in texto:
                    card["nro_asiento"] = texto.replace("Nro. Asiento:", "").strip()
                elif "Acto." in texto:
                    card["acto"] = texto.replace("Acto. :", "").strip()
                elif "Año:" in texto:
                    # "Año: 2012 Rubro: ..."
                    partes = texto.split("Rubro:")
                    card["año"] = partes[0].replace("Año:", "").strip()
                    card["rubro"] = partes[1].strip() if len(partes) > 1 else ""
                elif "Páginas:" in texto:
                    # Extraer todos los números de página
                    paginas = await div.query_selector_all("span.clickeable")
                    card["paginas"] = [
                        (await p.inner_text()).strip() for p in paginas
                    ]

        except Exception as e:
            print(f"  ⚠️  Error en card #{i+1}: {e}")

        resultados.append({
            "partida": encabezado.get("partida", "N/A"),
            "titulo": card.get("titulo", "N/A"),
            "acto": card.get("acto", "N/A")
        })
        print(f"  ✅ Card #{i+1}: {card.get('acto', 'Sin acto')} | "
              f"Asiento: {card.get('nro_asiento', '?')} | "
              f"Año: {card.get('año', '?')}")

    return resultados

async def navegar_siguelo(page):
    """Navega a la segunda página de SUNARP"""
    print("🌐 Navegando a siguelo.sunarp.gob.pe...")
    await page.goto(
        "https://siguelo.sunarp.gob.pe/siguelo/",
        wait_until="networkidle",
        timeout=60000
    )
    await esperar_cloudflare(page)
    print("✅ Página siguelo cargada")

async def clic_acepto(page):
    """Hace clic en el botón Acepto (btn-sunarp-cyan, no el No Acepto)"""
    print("🔘 Haciendo clic en Acepto...")
    await page.wait_for_selector("button.btn-sunarp-cyan", timeout=15000)
    await page.click("button.btn-sunarp-cyan")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2000)
    print("✅ Clic en Acepto realizado")

async def seleccionar_oficina(page, oficina="TACNA"):
    """Selecciona la oficina registral en el select nativo"""
    print(f"🏢 Seleccionando oficina: {oficina}...")
    await page.wait_for_selector("select#cboOficina", timeout=15000)
    await page.select_option("select#cboOficina", label=oficina.strip())
    await page.wait_for_timeout(800)
    print(f"✅ Oficina seleccionada: {oficina}")

async def seleccionar_anio(page, anio="2012"):
    """Selecciona el año de título"""
    print(f"📅 Seleccionando año: {anio}...")
    await page.wait_for_selector("select#cboAnio", timeout=15000)
    await page.select_option("select#cboAnio", value=str(anio))
    await page.wait_for_timeout(800)
    print(f"✅ Año seleccionado: {anio}")

async def escribir_numero_titulo(page, numero="2012"):
    """Escribe el número de título"""
    print(f"✍️  Escribiendo número de título: {numero}...")
    await page.wait_for_selector(
        "input[name='numeroTitulo']",
        timeout=15000
    )
    await page.fill("input[name='numeroTitulo']", str(numero))
    await page.wait_for_timeout(600)
    print("✅ Número de título ingresado")

async def clic_acceder_asiento(page):
    """Hace clic en el botón 'Acceder al asiento de inscripción y TIVE'"""
    print("📋 Haciendo clic en Acceder al asiento...")
    try:
        await page.wait_for_selector(
            "a[mat-button] span.mat-button-wrapper",
            timeout=15000
        )
        # Buscar por texto para asegurarnos del botón correcto
        botones = await page.query_selector_all("a[mat-button]")
        for boton in botones:
            texto = await boton.inner_text()
            if "asiento" in texto.lower() or "tive" in texto.lower():
                await boton.click()
                print("✅ Clic en Acceder al asiento realizado")
                await page.wait_for_timeout(2000)
                return
        print("⚠️  Botón no encontrado, intentando selector directo...")
        await page.click("a[mat-button]")
    except Exception as e:
        error_msg = f"Error al hacer clic en Acceder al asiento: {str(e)}"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)

async def clic_ojito_modal(page):
    """Hace clic en el botón del ojito (visibility) en el modal"""
    print("👁️  Buscando botón ojito en modal...")
    try:
        await page.wait_for_selector(
            "button.btn-success mat-icon",
            timeout=15000
        )
        botones = await page.query_selector_all("button.btn-success")
        if botones:
            await botones[0].click()
            print(f"✅ Clic en ojito (fila 1 de {len(botones)})")
            await page.wait_for_timeout(3000)
        else:
            raise Exception("No se encontró el botón ojito")
    except Exception as e:
        error_msg = f"Error al hacer clic en botón ojito: {str(e)}"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)

async def extraer_pdf_blob(page):
    """Intercepta y descarga el PDF blob, luego extrae su texto"""
    print("📄 Esperando apertura del PDF...")

    pdf_texto = None

    # Interceptar la nueva pestaña/popup con el PDF
    async with page.expect_popup() as popup_info:
        # El PDF ya debería haberse abierto, esperamos el popup
        pass

    try:
        popup = await popup_info.value
        pdf_url = popup.url
        print(f"🔗 URL del PDF: {pdf_url}")

        if pdf_url.startswith("blob:"):
            # Extraer el contenido del blob desde el contexto del popup
            pdf_bytes = await popup.evaluate("""
                async () => {
                    const response = await fetch(window.location.href);
                    const buffer = await response.arrayBuffer();
                    return Array.from(new Uint8Array(buffer));
                }
            """)

            # Convertir a bytes y guardar
            import io
            pdf_data = bytes(pdf_bytes)
            with open("documento_sunarp.pdf", "wb") as f:
                f.write(pdf_data)
            print("💾 PDF guardado como documento_sunarp.pdf")

            # Extraer texto del PDF
            pdf_texto = await extraer_texto_pdf(pdf_data)

        await popup.close()

    except Exception as e:
        print(f"⚠️  Error con popup: {e}")
        # Plan B: capturar desde la página actual si no abrió popup
        try:
            pdf_url = page.url
            if "blob:" in pdf_url or ".pdf" in pdf_url:
                pdf_bytes = await page.evaluate("""
                    async () => {
                        const response = await fetch(window.location.href);
                        const buffer = await response.arrayBuffer();
                        return Array.from(new Uint8Array(buffer));
                    }
                """)
                pdf_data = bytes(pdf_bytes)
                with open("documento_sunarp.pdf", "wb") as f:
                    f.write(pdf_data)
                pdf_texto = await extraer_texto_pdf(pdf_data)
        except Exception as e2:
            print(f"❌ Error plan B: {e2}")

    return pdf_texto

async def extraer_texto_pdf(pdf_data):
    """Extrae el texto de los bytes del PDF usando pypdf"""
    try:
        import pypdf
        import io

        reader = pypdf.PdfReader(io.BytesIO(pdf_data))
        texto_completo = []

        print(f"📖 PDF tiene {len(reader.pages)} páginas")
        for i, pg in enumerate(reader.pages):
            texto = pg.extract_text()
            texto_completo.append({
                "pagina": i + 1,
                "contenido": texto
            })
            print(f"  📄 Página {i+1}: {len(texto)} caracteres extraídos")

        # Guardar texto en JSON
        import json
        with open("texto_pdf_sunarp.json", "w", encoding="utf-8") as f:
            json.dump(texto_completo, f, ensure_ascii=False, indent=2)
        print("💾 Texto guardado en texto_pdf_sunarp.json")

        return texto_completo

    except ImportError:
        print("⚠️  pypdf no instalado. Ejecuta: pip install pypdf")
        return None
    except Exception as e:
        print(f"❌ Error extrayendo texto: {e}")
        return None


async def descargar_pdf_blob(page):
    """Intercepta el popup del PDF y lo descarga"""
    print("📥 Esperando PDF para descargar...")

    async with page.expect_popup() as popup_info:
        await clic_ojito_modal(page)

    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    pdf_url = popup.url
    print(f"🔗 PDF URL: {pdf_url}")

    try:
        pdf_bytes = await popup.evaluate("""
            async () => {
                const response = await fetch(window.location.href);
                const buffer = await response.arrayBuffer();
                return Array.from(new Uint8Array(buffer));
            }
        """)

        pdf_data = bytes(pdf_bytes)

        # Nombre con timestamp para no sobreescribir
        from datetime import datetime
        nombre = f"sunarp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        with open(nombre, "wb") as f:
            f.write(pdf_data)

        print(f"✅ PDF descargado: {nombre} ({len(pdf_data)/1024:.1f} KB)")
        await popup.close()
        return nombre

    except Exception as e:
        print(f"❌ Error descargando PDF: {e}")
        await popup.close()
        return None



async def descargar_pdf_como_screenshots(page, nombre_carpeta=None):
    """Scrollea dentro del visor PDF y captura cada sección"""
    print("📸 Capturando PDF por scroll...")

    async with page.expect_popup() as popup_info:
        await clic_ojito_modal(page)

    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    await popup.wait_for_timeout(3000)

    from datetime import datetime
    import os

     # ── Nombre de carpeta personalizado o timestamp por defecto ──
    if nombre_carpeta:
        carpeta = nombre_carpeta
    else:
        carpeta = f"sunarp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    os.makedirs(carpeta, exist_ok=True)

    archivos = []

    try:
        await popup.set_viewport_size({"width": 1280, "height": 1600})
        await popup.wait_for_timeout(1000)

        # ── Usar #viewerContainer que sabemos que scrollea ──
        sel = "#viewerContainer"

        dimensiones = await popup.evaluate(f"""
            () => {{
                const el = document.querySelector('{sel}');
                return {{
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight
                }};
            }}
        """)

        scroll_total  = dimensiones["scrollHeight"]
        viewport_h    = dimensiones["clientHeight"]
        overlap       = 50   # solapamiento mínimo, el visor ya pagina bien
        scroll_actual = 0
        num_captura   = 1

        print(f"📐 Altura total: {scroll_total}px | Viewport: {viewport_h}px")

        while scroll_actual <= scroll_total:
            # Scrollear dentro del viewerContainer
            await popup.evaluate(f"""
                () => {{
                    const el = document.querySelector('{sel}');
                    el.scrollTop = {scroll_actual};
                }}
            """)
            await popup.wait_for_timeout(1200)  # esperar render PDF

            # Verificar posición real
            pos_real = await popup.evaluate(f"""
                () => document.querySelector('{sel}').scrollTop
            """)

            # Capturar SOLO el elemento viewerContainer, no toda la página
            elemento = await popup.query_selector(sel)
            nombre_archivo = os.path.join(carpeta, f"pagina_{num_captura:02d}.png")
            await elemento.screenshot(path=nombre_archivo)

            archivos.append(nombre_archivo)
            print(f"  ✅ Captura {num_captura}: scroll {pos_real}px → {nombre_archivo}")

            # Detectar fin del documento
            if num_captura > 1 and pos_real < scroll_actual - 50:
                print("🏁 Llegamos al final del documento")
                break

            scroll_actual += viewport_h - overlap
            num_captura   += 1

            if num_captura > 50:
                print("⚠️  Límite de 50 capturas alcanzado")
                break

        print(f"\n🎉 {len(archivos)} imágenes guardadas en: {carpeta}/")

        # ── Solo imágenes, no se crea PDF ──

    except Exception as e:
        print(f"❌ Error: {e}")
        nombre_archivo = os.path.join(carpeta, "pagina_01.png")
        await popup.screenshot(path=nombre_archivo, full_page=True)
        archivos.append(nombre_archivo)

    await popup.close()
    return carpeta, archivos

# ── Funciones obsoletas de Gemini eliminadas ──
# El OCR ahora se hace directamente en procesar_card_siguelo usando Tesseract

async def debug_visor_pdf(page):
    """Inspecciona la estructura del visor PDF"""
    async with page.expect_popup() as popup_info:
        await clic_ojito_modal(page)

    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    await popup.wait_for_timeout(3000)

    info = await popup.evaluate("""
        () => {
            const elementos = ['#viewerContainer','#viewer','.pdfViewer',
                               'embed','iframe','body','html'];
            return elementos.map(sel => {
                const el = document.querySelector(sel);
                if (!el) return { sel, existe: false };
                return {
                    sel,
                    existe: true,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    overflow: getComputedStyle(el).overflow,
                    overflowY: getComputedStyle(el).overflowY,
                };
            });
        }
    """)

    print("\n🔍 DEBUG - Elementos del visor:")
    for el in info:
        if el["existe"]:
            print(f"  {el['sel']:25} | scroll: {el['scrollHeight']:5}px | "
                  f"client: {el['clientHeight']:5}px | overflow-y: {el['overflowY']}")

    await popup.close()

async def clic_buscar_siguelo(page):
    """Hace clic en el botón BUSCAR de siguelo"""
    print("🔍 Haciendo clic en BUSCAR...")
    try:
        await page.wait_for_selector(
            "button.btn.btn-sm.btn-block",
            timeout=10000
        )
        await page.click("button.btn.btn-sm.btn-block")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        print("✅ Búsqueda ejecutada")
    except Exception as e:
        error_msg = f"Error al hacer clic en botón BUSCAR: {str(e)}"
        print(f"❌ {error_msg}")
        raise Exception(error_msg)

async def seleccionar_area_registral(page, opcion_texto):
    """Selecciona el segundo dropdown (Área Registral) por texto exacto"""
    print(f"🔽 Seleccionando Área Registral: {opcion_texto}...")

    # Buscar el nz-select dentro del componente app-select con label "Area registral"
    await page.wait_for_selector("app-select nz-select", timeout=10000)

    # Clic en el segundo dropdown (Área Registral)
    select_area = await page.query_selector_all("app-select nz-select-top-control")
    if select_area:
        await select_area[0].click()
        await page.wait_for_timeout(800)

        # Esperar opciones y seleccionar
        await page.wait_for_selector("nz-option-item", timeout=10000)
        opciones = await page.query_selector_all("nz-option-item")
        for opcion in opciones:
            texto = await opcion.inner_text()
            if opcion_texto.upper() in texto.upper():
                await opcion.click()
                print(f"  ✅ Seleccionado: {texto.strip()}")
                await page.wait_for_timeout(800)
                return

    print(f"  ⚠️  No se encontró '{opcion_texto}'")

async def scrape(ciudad=None, placa=None, usuario=None, password=None):
    """
    Función principal de scraping
    
    Args:
        ciudad: Ciudad a buscar (ej: "CHIMBOTE")
        placa: Placa a buscar (ej: "H1M467")
        usuario: Usuario para login (si None, usa variable global)
        password: Contraseña para login (si None, usa variable global)
    
    Returns:
        dict: Resultado con datos extraídos y análisis OCR, incluyendo lista de archivos creados
    """
    # Usar parámetros o valores por defecto
    ciudad_final = (ciudad or CIUDAD).upper()
    placa_final = (placa or PLACA).upper()
    usuario_final = usuario or USUARIO
    password_final = password or PASSWORD
    
    # Lista para rastrear archivos/carpetas creados
    archivos_creados = {
        "carpetas": [],
        "json_final": None
    }
    
    # Detectar sistema operativo automáticamente
    import platform
    sistema_os = "windows" if platform.system() == "Windows" else "linux"
    
    try:
        async with async_playwright() as p:

            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
        
            context = await browser.new_context(
                locale="es-PE",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                viewport={"width": 1366, "height": 768}
            )
        
            page = await context.new_page()

            # ── Paso 1: Cargar página con retry y manejo de errores ──
            test_url = "https://sprl.sunarp.gob.pe/sprl/ingreso"  # URL ORIGINAL
            
            max_retries = 3
            page_loaded = False
            
            for attempt in range(max_retries):
                try:
                    print(f"🌐 Intento {attempt + 1}/{max_retries}: Cargando página {test_url}...")
                    await page.goto(
                        test_url,
                        wait_until="domcontentloaded",  # Cambiado de networkidle a domcontentloaded
                        timeout=120000  # Aumentado a 2 minutos
                    )
                    print("✅ Página cargada exitosamente")
                    page_loaded = True
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f"❌ Error después de {max_retries} intentos: {e}")
                        raise Exception(f"No se pudo cargar la página después de {max_retries} intentos: {str(e)}")
                    print(f"⚠️  Intento {attempt + 1}/{max_retries} fallido, reintentando en 5 segundos...")
                    await asyncio.sleep(5)
            
            if not page_loaded:
                raise Exception("No se pudo cargar la página después de todos los intentos")

            # ── Paso 2: Cloudflare principal (solo si es sunarp) ──
            if "sunarp" in test_url.lower():
                print("⏳ Esperando que pases el Cloudflare inicial...")
                await esperar_cloudflare(page)
            else:
                # Si es una URL de prueba, devolver resultado de prueba
                print("🧪 Modo prueba: URL de prueba detectada, devolviendo resultado simulado...")
                return {
                    "success": True,
                    "ciudad": ciudad_final,
                    "placa": placa_final,
                    "total_registros": 0,
                    "exitosos": 0,
                    "fallidos": 0,
                    "con_analisis": 0,
                    "duracion_segundos": 0,
                    "archivo_json": None,
                    "datos": [],
                    "archivos_creados": {"carpetas": [], "json_final": None},
                    "test_mode": True,
                    "message": f"Prueba exitosa: Página {test_url} cargada correctamente"
                }

            # ── Paso 3: Clic en botón INGRESAR (primera pantalla) ──
            try:
                print("🔍 Buscando botón INGRESAR...")
                await page.wait_for_selector("button.login-form-button", timeout=30000)
                await page.click("button.login-form-button")
                print("✅ Clic en INGRESAR realizado")
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"❌ Error en Paso 3 (clic INGRESAR): {e}")
                raise Exception(f"Error al hacer clic en botón INGRESAR: {str(e)}")

            # ── Paso 4: Llenar credenciales ──
            try:
                print("✍️  Escribiendo usuario...")
                await page.wait_for_selector("input[name='username']", timeout=15000)
                await page.fill("input[name='username']", usuario_final)
                await page.wait_for_timeout(600)

                print("✍️  Escribiendo contraseña...")
                await page.fill("input[name='password']", password_final)
                await page.wait_for_timeout(600)
            except Exception as e:
                print(f"❌ Error en Paso 4 (llenar credenciales): {e}")
                raise Exception(f"Error al llenar credenciales: {str(e)}")

            # ── Paso 5: Submit login ──
            try:
                print("🔐 Enviando credenciales...")
                await page.click("button[type='submit'].btn")
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(3000)
                print("📄 URL tras login:", page.url)
            except Exception as e:
                print(f"❌ Error en Paso 5 (submit login): {e}")
                raise Exception(f"Error al enviar credenciales: {str(e)}")

            # ── Paso 6: Turnstile interno ──
            try:
                await hacer_clic_turnstile(page)
                await esperar_turnstile_resuelto(page)
            except Exception as e:
                print(f"⚠️  Advertencia en Paso 6 (Turnstile): {e}")
                # Continuar aunque falle el turnstile

            # ── Paso 7: Primer dropdown → CIUDAD ──
            try:
                await seleccionar_dropdown_nz(page, index=0, texto_buscar=ciudad_final)
                await page.wait_for_timeout(1000)
            except Exception as e:
                print(f"❌ Error en Paso 7 (seleccionar ciudad): {e}")
                raise Exception(f"Error al seleccionar ciudad: {str(e)}")

            # ── Paso 8: Segundo dropdown → Propiedad Vehicular ──
            try:
                await seleccionar_area_registral(page, "Propiedad Vehicular")
            except Exception as e:
                print(f"❌ Error en Paso 8 (seleccionar área registral): {e}")
                raise Exception(f"Error al seleccionar área registral: {str(e)}")

            # ── Paso 9: Escribir número a buscar ──
            try:
                await escribir_numero_busqueda(page, placa_final)
            except Exception as e:
                print(f"❌ Error en Paso 9 (escribir número): {e}")
                raise Exception(f"Error al escribir número de búsqueda: {str(e)}")

            # ── Paso 10: Clic en Buscar ──
            try:
                await clic_buscar(page)
            except Exception as e:
                print(f"❌ Error en Paso 10 (clic buscar): {e}")
                raise Exception(f"Error al hacer clic en buscar: {str(e)}")

            # ── Paso 11: Turnstile post-búsqueda ──
            try:
                await esperar_y_resolver_turnstile_busqueda(page)
            except Exception as e:
                print(f"⚠️  Advertencia en Paso 11 (Turnstile post-búsqueda): {e}")
                # Continuar aunque falle el turnstile

            # ── Paso 12: Clic en botón detalle de la tabla ──
            try:
                await clic_boton_detalle_tabla(page)
            except Exception as e:
                print(f"❌ Error en Paso 12 (clic detalle tabla): {e}")
                raise Exception(f"Error al hacer clic en detalle de tabla: {str(e)}")

            # ── Paso 13: Extraer datos del drawer ──
            try:
                datos = await extraer_datos_drawer(page)
            except Exception as e:
                print(f"❌ Error en Paso 13 (extraer datos drawer): {e}")
                raise Exception(f"Error al extraer datos del drawer: {str(e)}")
            
            try:
                with open("resultado_sunarp.json", "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, indent=2)
                print(f"\n💾 Guardado en resultado_sunarp.json")
            except Exception as e:
                print(f"⚠️  Advertencia al guardar resultado_sunarp.json: {e}")

            # ── Paso 14: Procesar todos los cards de siguelo ──
            try:
                MODO = "secuencial"
                LIMITE_PARALELO = 3

                print(f"\n🎯 Procesando {len(datos)} cards en modo: {MODO.upper()}")
                inicio = datetime.now()

                if MODO == "secuencial":
                    resultados_pdf = await procesar_secuencial(browser, datos, ciudad_final)

                # ── Recopilar carpetas creadas para limpieza posterior ──
                carpetas_creadas = []
                for resultado in resultados_pdf:
                    if isinstance(resultado, dict) and "carpeta_creada" in resultado:
                        carpeta = resultado["carpeta_creada"]
                        if carpeta and os.path.exists(carpeta):
                            carpetas_creadas.append(carpeta)
                archivos_creados["carpetas"] = carpetas_creadas

                # ── Resumen final ──
                duracion = (datetime.now() - inicio).seconds
                exitosos = [r for r in resultados_pdf if isinstance(r, dict) and "error" not in r]
                fallidos  = [r for r in resultados_pdf if isinstance(r, dict) and "error" in r]
                con_analisis = [r for r in exitosos if "analisis_ia" in r and r.get("analisis_ia") and r.get("analisis_ia").get("texto_completo")]

                print(f"\n{'='*50}")
                print(f"✅ Exitosos : {len(exitosos)}/{len(datos)}")
                print(f"❌ Fallidos : {len(fallidos)}/{len(datos)}")
                print(f"📖 Con análisis OCR: {len(con_analisis)}/{len(exitosos)}")
                print(f"⏱️  Duración : {duracion} segundos")
                print(f"{'='*50}")
            
                # ── Paso 15: Guardar JSON final con análisis ──
                print("\n💾 Guardando JSON final con análisis OCR...")
                
                json_final = []
                for resultado in resultados_pdf:
                    if "error" in resultado:
                        json_final.append({
                            "card": resultado.get("card", {}),
                            "error": resultado.get("error"),
                            "analisis_ia": None
                        })
                    else:
                        # Solo mantener texto_completo en analisis_ia
                        analisis_ia = resultado.get("analisis_ia", {})
                        if isinstance(analisis_ia, dict) and "texto_completo" in analisis_ia:
                            analisis_ia = {"texto_completo": analisis_ia["texto_completo"]}
                        
                        json_final.append({
                            "card": resultado.get("card", {}),
                            "analisis_ia": analisis_ia
                        })
                
                nombre_json_final = f"resultado_final_con_ia_{ciudad_final}_{placa_final}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(nombre_json_final, "w", encoding="utf-8") as f:
                    json.dump(json_final, f, ensure_ascii=False, indent=2)
                
                archivos_creados["json_final"] = nombre_json_final
                
                print(f"✅ JSON final guardado: {nombre_json_final}")
                print(f"   Total de registros: {len(json_final)}")
                print(f"   Con análisis OCR: {len(con_analisis)}")
                
                return {
                    "success": True,
                    "ciudad": ciudad_final,
                    "placa": placa_final,
                    "total_registros": len(json_final),
                    "exitosos": len(exitosos),
                    "fallidos": len(fallidos),
                    "con_analisis": len(con_analisis),
                    "duracion_segundos": duracion,
                    "archivo_json": nombre_json_final,
                    "datos": json_final,
                    "archivos_creados": archivos_creados  # Información para limpieza
                }
            except Exception as e:
                print(f"❌ Error en Paso 14-15 (procesar cards): {e}")
                raise Exception(f"Error al procesar cards: {str(e)}")
    
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"❌ Error general en función scrape: {str(e)}")
        print(f"❌ Traceback completo:\n{error_traceback}")
        raise Exception(f"Error en scraping: {str(e)}")

# ── Ejecutar solo si se llama directamente ──
if __name__ == "__main__":
    asyncio.run(scrape())
