from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
import os
import shutil
import traceback
from test_camoufox5 import scrape

# Cargar variables de entorno desde .env
load_dotenv()
if os.getenv("GITHUB_TOKEN"):
    os.environ["GH_TOKEN"] = os.getenv("GITHUB_TOKEN")
app = FastAPI(
    title="SUNARP Scraper API",
    description="API para scraping de SUNARP usando Camoufox",
    version="1.0.0"
)

# ── Configurar CORS para permitir peticiones desde frontend desplegado ──
# Obtener orígenes permitidos desde .env o permitir todos por defecto
allowed_origins = os.getenv('CORS_ORIGINS', '*').split(',')
if '*' in allowed_origins:
    allowed_origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Manejo global de excepciones para evitar que el servidor se caiga
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Captura todas las excepciones no manejadas y devuelve una respuesta JSON"""
    error_traceback = traceback.format_exc()
    print(f"❌ Error no manejado en {request.url.path}: {str(exc)}")
    print(f"❌ Traceback completo:\n{error_traceback}")
    
    # Determinar código de estado apropiado
    status_code = 500
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": True,
            "message": str(exc),
            "detail": "Error interno del servidor. El error ha sido registrado.",
            "path": str(request.url.path)
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Maneja errores de validación de Pydantic"""
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "message": "Error de validación en los parámetros",
            "detail": str(exc.errors())
        }
    )

# Modelo Pydantic para el body del POST
class ScrapeRequest(BaseModel):
    ciudad: Optional[str] = None
    placa: Optional[str] = None

def limpiar_archivos(archivos_creados):
    """Elimina carpetas y archivos creados durante el scraping"""
    try:
        # Eliminar carpetas
        for carpeta in archivos_creados.get("carpetas", []):
            if os.path.exists(carpeta):
                shutil.rmtree(carpeta)
                print(f"🗑️  Carpeta eliminada: {carpeta}")
        
        # Eliminar archivo JSON
        json_final = archivos_creados.get("json_final")
        if json_final and os.path.exists(json_final):
            os.remove(json_final)
            print(f"🗑️  Archivo JSON eliminado: {json_final}")
    except Exception as e:
        print(f"⚠️  Error al limpiar archivos: {e}")

@app.get('/health')
async def health():
    """Endpoint de salud para verificar que el servidor está funcionando"""
    return {"status": "ok", "message": "Servidor funcionando correctamente"}

@app.get('/ngrok-url')
async def get_ngrok_url():
    """Endpoint para obtener la URL pública de ngrok (si está activo)"""
    try:
        from pyngrok import ngrok
        tunnels = ngrok.get_tunnels()
        if tunnels:
            public_url = tunnels[0].public_url
            return {
                "ngrok_active": True,
                "public_url": public_url,
                "message": "Ngrok está activo y la API es accesible públicamente"
            }
        else:
            return {
                "ngrok_active": False,
                "public_url": None,
                "message": "Ngrok no está activo"
            }
    except Exception as e:
        return {
            "ngrok_active": False,
            "public_url": None,
            "error": str(e),
            "message": "Error al verificar estado de ngrok"
        }

@app.post('/scrape')
async def scrape_endpoint(request_body: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Endpoint para ejecutar el scraping de SUNARP
    
    Body JSON esperado:
    {
        "ciudad": "CHIMBOTE",  # Opcional, si no se envía usa valor por defecto
        "placa": "H1M467"      # Opcional, si no se envía usa valor por defecto
    }
    
    Las credenciales (USUARIO y PASSWORD) se leen desde el archivo .env
    """
    archivos_creados = {"carpetas": [], "json_final": None}
    
    try:
        # Obtener datos del body JSON
        ciudad = request_body.ciudad
        placa = request_body.placa
        
        # Obtener credenciales desde .env
        usuario = os.getenv('USUARIO')
        password = os.getenv('PASSWORD')
        
        if not usuario or not password:
            raise HTTPException(
                status_code=400,
                detail="Credenciales no configuradas en .env. Verifica que USUARIO y PASSWORD estén definidos."
            )
        
        # Validar que se envíen ciudad y placa
        if not ciudad or not placa:
            raise HTTPException(
                status_code=400,
                detail="Se requieren los parámetros 'ciudad' y 'placa' en el body JSON"
            )
        
        # Ejecutar el scraping de forma asíncrona
        print(f"🚀 Iniciando scraping para ciudad: {ciudad}, placa: {placa}")
        
        try:
            resultado = await scrape(
                ciudad=ciudad,
                placa=placa,
                usuario=usuario,
                password=password
            )
            
            # Extraer información de archivos creados antes de limpiar
            archivos_creados = resultado.get("archivos_creados", {"carpetas": [], "json_final": None})
            
            # Preparar respuesta sin incluir archivos_creados
            respuesta = {k: v for k, v in resultado.items() if k != "archivos_creados"}
            
            # Programar limpieza de archivos después de enviar la respuesta
            background_tasks.add_task(limpiar_archivos, archivos_creados)
            
            return respuesta
            
        except Exception as scrape_error:
            # Capturar errores específicos del scraping (URLs, timeouts, etc.)
            error_msg = str(scrape_error)
            print(f"❌ Error durante scraping: {error_msg}")
            print(f"❌ Tipo de error: {type(scrape_error).__name__}")
            
            # Limpiar archivos incluso si hay error
            try:
                limpiar_archivos(archivos_creados)
            except Exception as cleanup_error:
                print(f"⚠️  Error al limpiar archivos: {cleanup_error}")
            
            # Determinar código de estado según el tipo de error
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                status_code = 504  # Gateway Timeout
                detail = f"Timeout al intentar acceder a la URL: {error_msg}"
            elif "network" in error_msg.lower() or "connection" in error_msg.lower() or "url" in error_msg.lower():
                status_code = 502  # Bad Gateway
                detail = f"Error de conexión o URL inválida: {error_msg}"
            else:
                status_code = 500
                detail = f"Error durante el scraping: {error_msg}"
            
            raise HTTPException(status_code=status_code, detail=detail)
        
    except HTTPException:
        # Limpiar archivos antes de re-lanzar HTTPException
        try:
            limpiar_archivos(archivos_creados)
        except Exception as cleanup_error:
            print(f"⚠️  Error al limpiar archivos: {cleanup_error}")
        raise
    except Exception as e:
        # Capturar cualquier otro error no esperado
        error_traceback = traceback.format_exc()
        print(f"❌ Error inesperado en endpoint POST /scrape: {e}")
        print(f"❌ Traceback:\n{error_traceback}")
        
        # Limpiar archivos incluso si hay error
        try:
            limpiar_archivos(archivos_creados)
        except Exception as cleanup_error:
            print(f"⚠️  Error al limpiar archivos: {cleanup_error}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.get('/scrape')
async def scrape_get(
    ciudad: Optional[str] = Query(None, description="Ciudad para el scraping"),
    placa: Optional[str] = Query(None, description="Placa para el scraping"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Endpoint GET con parámetros en query string (alternativa)"""
    archivos_creados = {"carpetas": [], "json_final": None}
    
    try:
        # Obtener credenciales desde .env
        usuario = os.getenv('USUARIO')
        password = os.getenv('PASSWORD')
        
        if not usuario or not password:
            raise HTTPException(
                status_code=400,
                detail="Credenciales no configuradas en .env"
            )
        
        if not ciudad or not placa:
            raise HTTPException(
                status_code=400,
                detail="Se requieren los parámetros 'ciudad' y 'placa' en la URL (ej: /scrape?ciudad=CHIMBOTE&placa=H1M467)"
            )
        
        # Ejecutar el scraping
        print(f"🚀 Iniciando scraping para ciudad: {ciudad}, placa: {placa}")
        
        try:
            resultado = await scrape(
                ciudad=ciudad,
                placa=placa,
                usuario=usuario,
                password=password
            )
            
            # Extraer información de archivos creados antes de limpiar
            archivos_creados = resultado.get("archivos_creados", {"carpetas": [], "json_final": None})
            
            # Preparar respuesta sin incluir archivos_creados
            respuesta = {k: v for k, v in resultado.items() if k != "archivos_creados"}
            
            # Programar limpieza de archivos después de enviar la respuesta
            background_tasks.add_task(limpiar_archivos, archivos_creados)
            
            return respuesta
            
        except Exception as scrape_error:
            # Capturar errores específicos del scraping (URLs, timeouts, etc.)
            error_msg = str(scrape_error)
            print(f"❌ Error durante scraping: {error_msg}")
            print(f"❌ Tipo de error: {type(scrape_error).__name__}")
            
            # Limpiar archivos incluso si hay error
            try:
                limpiar_archivos(archivos_creados)
            except Exception as cleanup_error:
                print(f"⚠️  Error al limpiar archivos: {cleanup_error}")
            
            # Determinar código de estado según el tipo de error
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                status_code = 504  # Gateway Timeout
                detail = f"Timeout al intentar acceder a la URL: {error_msg}"
            elif "network" in error_msg.lower() or "connection" in error_msg.lower() or "url" in error_msg.lower():
                status_code = 502  # Bad Gateway
                detail = f"Error de conexión o URL inválida: {error_msg}"
            else:
                status_code = 500
                detail = f"Error durante el scraping: {error_msg}"
            
            raise HTTPException(status_code=status_code, detail=detail)
        
    except HTTPException:
        # Limpiar archivos antes de re-lanzar HTTPException
        try:
            limpiar_archivos(archivos_creados)
        except Exception as cleanup_error:
            print(f"⚠️  Error al limpiar archivos: {cleanup_error}")
        raise
    except Exception as e:
        # Capturar cualquier otro error no esperado
        error_traceback = traceback.format_exc()
        print(f"❌ Error inesperado en endpoint GET /scrape: {e}")
        print(f"❌ Traceback:\n{error_traceback}")
        
        # Limpiar archivos incluso si hay error
        try:
            limpiar_archivos(archivos_creados)
        except Exception as cleanup_error:
            print(f"⚠️  Error al limpiar archivos: {cleanup_error}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Error interno del servidor: {str(e)}"
        )

if __name__ == '__main__':
    import uvicorn
    
    # Verificar que existan las credenciales
    usuario = os.getenv('USUARIO')
    password = os.getenv('PASSWORD')
    
    if not usuario or not password:
        print("⚠️  ADVERTENCIA: USUARIO y/o PASSWORD no están definidos en .env")
        print("   El servidor iniciará pero los requests fallarán hasta configurar las credenciales")
    
    # Obtener puerto desde variable de entorno (para Hugging Face Spaces) o usar 5000 por defecto
    port = int(os.getenv('PORT', 5000))
    
    # ── Iniciar ngrok automáticamente si está habilitado ──
    ngrok_enabled = os.getenv('NGROK_ENABLED', 'true').lower() == 'true'
    ngrok_auth_token = os.getenv('NGROK_AUTH_TOKEN', None)
    public_url = None
    
    if ngrok_enabled:
        try:
            from pyngrok import ngrok, conf
            
            # Configurar token de autenticación si está disponible (opcional pero recomendado)
            if ngrok_auth_token:
                conf.get_default().auth_token = ngrok_auth_token
                print("✅ Token de ngrok configurado")
            
            # Iniciar túnel ngrok
            print("🚇 Iniciando túnel ngrok...")
            public_url = ngrok.connect(port, bind_tls=True)
            print(f"✅ Ngrok activo!")
            print(f"🌐 URL pública: {public_url}")
            print(f"🔒 URL HTTPS: {public_url.replace('http://', 'https://')}")
            print(f"📋 Usa esta URL en tu frontend desplegado")
            print("")
        except ImportError:
            print("⚠️  pyngrok no está instalado. Instala con: pip install pyngrok")
            print("   O desactiva ngrok configurando NGROK_ENABLED=false en .env")
        except Exception as e:
            print(f"⚠️  Error al iniciar ngrok: {e}")
            print("   El servidor continuará sin ngrok (solo accesible localmente)")
    
    print("🌐 Iniciando servidor FastAPI...")
    print("📡 Endpoints disponibles:")
    print("   GET  /health - Verificar estado del servidor")
    print("   GET  /ngrok-url - Obtener URL pública de ngrok")
    print("   POST /scrape - Ejecutar scraping (body JSON con ciudad y placa)")
    print("   GET  /scrape?ciudad=CHIMBOTE&placa=H1M467 - Ejecutar scraping (query params)")
    print("   GET  /docs - Documentación interactiva (Swagger UI)")
    print("   GET  /redoc - Documentación alternativa (ReDoc)")
    print("")
    
    if public_url:
        print(f"🎯 Tu frontend puede consumir la API desde: {public_url}")
        print("")
    
    try:
        uvicorn.run(app, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo servidor...")
        if ngrok_enabled:
            try:
                from pyngrok import ngrok
                ngrok.kill()
                print("✅ Túnel ngrok cerrado")
            except:
                pass
