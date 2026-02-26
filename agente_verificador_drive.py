"""
AGENTE 3.5: Verificacion de Subida a Google Drive
- Verifica que cada obra haya subido sus archivos de tareo al Drive
- Busca dentro de la subcarpeta del mes (ej: "Feb-26")
- Verifica si hay archivos subidos en o despues de la fecha objetivo
"""
from config import OBRAS, MONTH_ABBREVS_ES


def verificar_subidas_drive(drive_service, fecha_objetivo):
    """
    Verifica si cada obra subio archivos a su carpeta de Google Drive.

    Args:
        drive_service: Google Drive API v3 service
        fecha_objetivo: date object (fecha del tareo)

    Returns:
        dict: {obra_key: {"subido": bool, "detalle": str, "archivos": list}}
    """
    resultados = {}
    month_folder_name = _nombre_carpeta_mes(fecha_objetivo)

    for obra_key, obra_info in OBRAS.items():
        folder_id = obra_info.get("drive_folder_id")
        if not folder_id:
            resultados[obra_key] = {
                "subido": False,
                "detalle": "Sin folder configurado",
                "archivos": [],
            }
            continue

        try:
            resultado = _verificar_obra(drive_service, folder_id, month_folder_name, fecha_objetivo)
            resultados[obra_key] = resultado
            status = "OK" if resultado["subido"] else "FALTA"
            print(f"  [DRIVE] {obra_info['nombre']}: {status} ({resultado['detalle']})")

        except Exception as e:
            print(f"  [DRIVE] Error verificando {obra_info['nombre']}: {e}")
            resultados[obra_key] = {
                "subido": False,
                "detalle": f"Error: {e}",
                "archivos": [],
            }

    return resultados


def _nombre_carpeta_mes(fecha):
    """Genera nombre de carpeta del mes: 'Feb-26' para febrero 2026."""
    month_abbrev = MONTH_ABBREVS_ES[fecha.month - 1]
    year_short = str(fecha.year)[-2:]
    return f"{month_abbrev}-{year_short}"


def _verificar_obra(drive_service, parent_folder_id, month_folder_name, fecha_objetivo):
    """Verifica una obra: busca carpeta del mes y archivos recientes."""
    resultado = {"subido": False, "detalle": "", "archivos": []}

    # Paso 1: Buscar la subcarpeta del mes
    month_folder_id = _buscar_carpeta_mes(drive_service, parent_folder_id, month_folder_name)
    if not month_folder_id:
        resultado["detalle"] = f"Carpeta '{month_folder_name}' no encontrada"
        return resultado

    # Paso 2: Buscar archivos subidos en o despues de la fecha objetivo
    archivos = _buscar_archivos_recientes(drive_service, month_folder_id, fecha_objetivo)

    if archivos:
        resultado["subido"] = True
        resultado["detalle"] = f"{len(archivos)} archivo(s) encontrado(s)"
        resultado["archivos"] = archivos
    else:
        resultado["detalle"] = f"Sin archivos desde {fecha_objetivo.strftime('%d/%m/%Y')}"

    return resultado


def _buscar_carpeta_mes(drive_service, parent_folder_id, month_folder_name):
    """
    Busca la subcarpeta del mes dentro del folder padre.
    Matching flexible: exacto -> contiene patron -> contiene abreviatura.
    """
    query = (
        f"'{parent_folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )

    results = drive_service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        pageSize=50,
    ).execute()

    folders = results.get("files", [])
    month_lower = month_folder_name.lower()
    abbrev_lower = month_folder_name.split("-")[0].lower()

    # Match exacto: "Feb-26"
    for f in folders:
        if f["name"] == month_folder_name:
            return f["id"]

    # Contiene patron: "2.Feb-26" o "02-Feb-26"
    for f in folders:
        if month_lower in f["name"].lower():
            return f["id"]

    # Contiene abreviatura del mes: "feb"
    for f in folders:
        if abbrev_lower in f["name"].lower():
            year_short = month_folder_name.split("-")[1]
            if year_short in f["name"]:
                return f["id"]

    return None


def _buscar_archivos_recientes(drive_service, folder_id, fecha_objetivo):
    """
    Busca archivos en la carpeta del mes creados en o despues de fecha_objetivo.
    """
    fecha_str = fecha_objetivo.strftime("%Y-%m-%dT00:00:00")

    query = (
        f"'{folder_id}' in parents "
        f"and trashed = false "
        f"and createdTime >= '{fecha_str}'"
    )

    results = drive_service.files().list(
        q=query,
        fields="files(id, name, createdTime, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        pageSize=20,
        orderBy="createdTime desc",
    ).execute()

    archivos = []
    for f in results.get("files", []):
        archivos.append({
            "nombre": f["name"],
            "creado": f.get("createdTime", ""),
            "modificado": f.get("modifiedTime", ""),
        })

    return archivos
