"""
Modulo de autenticacion OAuth2 con Gmail API.
- Local: reutiliza credenciales del proyecto gmail-comparativos-agent
- GitHub Actions: usa credenciales restauradas en la raiz del repo
"""
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import CREDENTIALS_FILE, TOKEN_FILE, SCOPES, BASE_DIR


_creds = None


def _obtener_credenciales():
    """Obtiene credenciales OAuth2, reutilizando si ya existen."""
    global _creds

    if _creds and _creds.valid:
        return _creds

    # En GitHub Actions, credenciales se restauran en la raiz del repo
    if os.environ.get("GITHUB_ACTIONS"):
        creds_file = os.path.join(BASE_DIR, "credentials.json")
        token_file = os.path.join(BASE_DIR, "token.json")
    else:
        creds_file = CREDENTIALS_FILE
        token_file = TOKEN_FILE

    creds = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[AUTH] Refrescando token expirado...")
            creds.refresh(Request())
        else:
            if os.environ.get("GITHUB_ACTIONS"):
                raise RuntimeError(
                    "[AUTH] Token expirado o invalido en GitHub Actions. "
                    "Regenera token.json localmente y actualiza el Secret GOOGLE_TOKEN."
                )

            if not os.path.exists(creds_file):
                raise FileNotFoundError(
                    f"Archivo de credenciales no encontrado: {creds_file}\n"
                    "Asegurate de que el proyecto gmail-comparativos-agent tenga credentials.json"
                )

            print("[AUTH] Iniciando flujo de autorizacion OAuth2...")
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w") as token:
            token.write(creds.to_json())
        print("[AUTH] Token guardado exitosamente.")

    _creds = creds
    return creds


def autenticar_gmail():
    """Retorna el servicio de Gmail API."""
    creds = _obtener_credenciales()
    service = build("gmail", "v1", credentials=creds)
    print("[AUTH] Conectado a Gmail API correctamente.")
    return service


def autenticar_drive():
    """Retorna el servicio de Google Drive API (readonly)."""
    creds = _obtener_credenciales()
    service = build("drive", "v3", credentials=creds)
    print("[AUTH] Conectado a Drive API correctamente.")
    return service


def obtener_perfil(service):
    """Obtiene el email del usuario autenticado."""
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "desconocido")
