#!/usr/bin/env python3
"""
Script para iniciar el servidor FastAPI con ngrok automáticamente
Este script es una alternativa más simple al inicio directo de app.py
"""

import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Verificar que pyngrok esté instalado
try:
    from pyngrok import ngrok, conf
except ImportError:
    print("❌ pyngrok no está instalado")
    print("📦 Instala con: pip install pyngrok")
    sys.exit(1)

def main():
    # Obtener configuración
    port = int(os.getenv('PORT', 5000))
    ngrok_enabled = os.getenv('NGROK_ENABLED', 'true').lower() == 'true'
    ngrok_auth_token = os.getenv('NGROK_AUTH_TOKEN', None)
    
    # Configurar token si está disponible
    if ngrok_auth_token:
        conf.get_default().auth_token = ngrok_auth_token
        print("✅ Token de ngrok configurado")
    
    # Iniciar ngrok si está habilitado
    public_url = None
    if ngrok_enabled:
        try:
            print("🚇 Iniciando túnel ngrok...")
            public_url = ngrok.connect(port, bind_tls=True)
            print(f"✅ Ngrok activo!")
            print(f"🌐 URL pública HTTPS: {public_url}")
            print("")
        except Exception as e:
            print(f"⚠️  Error al iniciar ngrok: {e}")
            print("   El servidor continuará sin ngrok")
    
    # Importar y ejecutar app
    print("🌐 Iniciando servidor FastAPI...")
    print(f"📡 Servidor local: http://localhost:{port}")
    if public_url:
        print(f"🌍 Servidor público: {public_url}")
        print("")
        print("🎯 Copia esta URL y úsala en tu frontend desplegado:")
        print(f"   {public_url}")
        print("")
    
    # Importar app y ejecutar
    import uvicorn
    from app import app
    
    try:
        uvicorn.run(app, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo servidor...")
        if public_url:
            try:
                ngrok.kill()
                print("✅ Túnel ngrok cerrado")
            except:
                pass

if __name__ == '__main__':
    main()
