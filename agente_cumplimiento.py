"""
AGENTE 3: Validacion de Cumplimiento y Notificacion
- Cruza obras que enviaron tareo vs. todas las registradas
- Clasifica: CUMPLIO, ENVIO TARDE (fecha incorrecta), NO ENVIO
- Envia correo de llamado de atencion a obras que no enviaron
- Envia notificaciones adicionales por formato incorrecto o falta de subida a Drive
"""
import json
import os
import base64
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

from config import OBRAS, NOTIFICACIONES_JSON, MODO_PRUEBA, TEST_EMAIL

# Zona horaria Peru (UTC-5)
PERU_TZ = timezone(timedelta(hours=-5))


def evaluar_cumplimiento(tareos_encontrados, fecha_objetivo, resultados_drive=None):
    """
    Evalua el cumplimiento de cada obra.

    Args:
        tareos_encontrados: Lista de dicts con datos de tareos (del agente 1 + agente 2)
        fecha_objetivo: date object (fecha esperada del tareo)
        resultados_drive: dict {obra_key: {"subido": bool, "detalle": str}} (opcional)

    Returns:
        dict con:
            cumplieron: lista de obras que cumplieron
            tareo_incorrecto: lista de obras que enviaron pero con fecha incorrecta
            no_enviaron: lista de obras que no enviaron
    """
    if resultados_drive is None:
        resultados_drive = {}

    # Mapear correos encontrados por obra_key
    tareos_por_obra = {}
    for tareo in tareos_encontrados:
        key = tareo["obra_key"]
        if key not in tareos_por_obra:
            tareos_por_obra[key] = tareo
        # Si hay multiples correos de la misma obra, quedarse con el mas reciente

    cumplieron = []
    tareo_incorrecto = []
    no_enviaron = []

    for obra_key, obra_info in OBRAS.items():
        drive_info = resultados_drive.get(obra_key, {})
        drive_ok = drive_info.get("subido", False)
        drive_detalle = drive_info.get("detalle", "No verificado")

        if obra_key in tareos_por_obra:
            tareo = tareos_por_obra[obra_key]
            datos = tareo.get("datos_excel", {})

            formato_ok = datos.get("formato_valido", False) if datos else False

            if datos and datos.get("fecha_correcta"):
                cumplieron.append({
                    "obra_key": obra_key,
                    "obra_nombre": obra_info["nombre"],
                    "estado": "CUMPLIO",
                    "tareo": tareo,
                    "datos": datos,
                    "formato_ok": formato_ok,
                    "drive_ok": drive_ok,
                    "drive_detalle": drive_detalle,
                })
            elif datos and datos.get("fecha_tareo"):
                tareo_incorrecto.append({
                    "obra_key": obra_key,
                    "obra_nombre": obra_info["nombre"],
                    "estado": "FECHA INCORRECTA",
                    "tareo": tareo,
                    "datos": datos,
                    "detalle": f"Tareo del {datos['fecha_tareo']} (esperado: {fecha_objetivo.strftime('%d/%m/%Y')})",
                    "formato_ok": formato_ok,
                    "drive_ok": drive_ok,
                    "drive_detalle": drive_detalle,
                })
            else:
                # Envio correo pero no se pudo extraer datos o no tiene fecha
                cumplieron.append({
                    "obra_key": obra_key,
                    "obra_nombre": obra_info["nombre"],
                    "estado": "ENVIO (sin datos Excel)",
                    "tareo": tareo,
                    "datos": datos or {},
                    "formato_ok": formato_ok,
                    "drive_ok": drive_ok,
                    "drive_detalle": drive_detalle,
                })
        else:
            no_enviaron.append({
                "obra_key": obra_key,
                "obra_nombre": obra_info["nombre"],
                "estado": "NO ENVIO",
                "emails_registrados": obra_info["emails"],
                "drive_ok": drive_ok,
                "drive_detalle": drive_detalle,
            })

    return {
        "cumplieron": cumplieron,
        "tareo_incorrecto": tareo_incorrecto,
        "no_enviaron": no_enviaron,
        "fecha_objetivo": fecha_objetivo.strftime("%d/%m/%Y"),
        "total_obras": len(OBRAS),
    }


def enviar_notificaciones(service, no_enviaron, fecha_objetivo, mi_email):
    """
    Envia correos de llamado de atencion a obras que no enviaron el tareo.

    Args:
        service: Gmail API service
        no_enviaron: Lista de obras que no cumplieron
        fecha_objetivo: date (fecha del tareo)
        mi_email: Email del usuario autenticado (remitente)

    Returns:
        Lista de resultados de envio
    """
    if not no_enviaron:
        print("[AGENTE 3] Todas las obras cumplieron. No hay notificaciones que enviar.")
        return []

    # Cargar registro de notificaciones previas
    notificaciones_previas = _cargar_notificaciones()

    resultados = []
    fecha_str = fecha_objetivo.strftime("%d/%m/%Y")

    for obra in no_enviaron:
        obra_key = obra["obra_key"]
        obra_nombre = obra["obra_nombre"]
        emails_destino = obra["emails_registrados"]
        emails_cc = OBRAS.get(obra_key, {}).get("emails_cc", [])

        # Verificar si ya se notifico hoy para esta obra
        noti_key = f"{obra_key}_{fecha_objetivo.isoformat()}"
        if noti_key in notificaciones_previas:
            print(f"  [SKIP] {obra_nombre} - ya notificada anteriormente")
            resultados.append({
                "obra_key": obra_key,
                "obra_nombre": obra_nombre,
                "estado": "YA NOTIFICADA",
                "emails": emails_destino,
            })
            continue

        # Construir correo de llamado de atencion
        asunto = f"[ALERTA] Regularizacion de Tareo Diario - {obra_nombre} - {fecha_str}"

        cuerpo = f"""Estimados,

Se ha detectado que {obra_nombre} no envio el Informe Diario de Personal de Obra (Tareo) correspondiente al dia {fecha_str}.

Se solicita regularizar el envio a la brevedad posible, enviando el archivo al correo correspondiente con el asunto "INFORME DIARIO DE PERSONAL DE OBRA".

Recordar que el tareo debe corresponder al mismo dia de envio.

Saludos cordiales,
Sistema Automatizado de Control y Gestión de Proyectos - HERGONSA
"""

        try:
            # Enviar a todos los emails de la obra con CC
            # En modo prueba, todo va al usuario de prueba
            msg = MIMEText(cuerpo)
            if MODO_PRUEBA:
                msg["to"] = TEST_EMAIL
            else:
                msg["to"] = ", ".join(emails_destino)
                if emails_cc:
                    msg["cc"] = ", ".join(emails_cc)
            msg["from"] = mi_email
            msg["subject"] = asunto

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            sent = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            if MODO_PRUEBA:
                print(f"  [OK] Notificacion enviada a {obra_nombre}: {TEST_EMAIL} (MODO PRUEBA)")
            else:
                cc_info = f" (CC: {len(emails_cc)} destinatarios)" if emails_cc else ""
                print(f"  [OK] Notificacion enviada a {obra_nombre}: {emails_destino}{cc_info}")

            # Registrar notificacion
            notificaciones_previas[noti_key] = {
                "obra": obra_nombre,
                "emails": emails_destino,
                "emails_cc": emails_cc,
                "fecha_tareo": fecha_str,
                "enviado_el": datetime.now(PERU_TZ).isoformat(),
                "gmail_id": sent["id"],
            }

            resultados.append({
                "obra_key": obra_key,
                "obra_nombre": obra_nombre,
                "estado": "NOTIFICACION ENVIADA",
                "emails": emails_destino,
                "emails_cc": emails_cc,
                "gmail_id": sent["id"],
            })

        except Exception as e:
            print(f"  [ERROR] Fallo al notificar a {obra_nombre}: {e}")
            resultados.append({
                "obra_key": obra_key,
                "obra_nombre": obra_nombre,
                "estado": f"ERROR: {e}",
                "emails": emails_destino,
            })

    # Guardar registro actualizado
    _guardar_notificaciones(notificaciones_previas)

    return resultados


def _cargar_notificaciones():
    """Carga el registro de notificaciones enviadas."""
    if os.path.exists(NOTIFICACIONES_JSON):
        try:
            with open(NOTIFICACIONES_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _guardar_notificaciones(notificaciones):
    """Guarda el registro de notificaciones enviadas."""
    os.makedirs(os.path.dirname(NOTIFICACIONES_JSON), exist_ok=True)
    with open(NOTIFICACIONES_JSON, "w", encoding="utf-8") as f:
        json.dump(notificaciones, f, ensure_ascii=False, indent=2)


def enviar_notificaciones_adicionales(service, resultado_cumplimiento, fecha_objetivo, mi_email):
    """
    Envia notificaciones a obras que SI enviaron correo pero tienen
    formato incorrecto y/o no subieron archivos al Drive.
    Un solo correo por obra combinando ambas observaciones si aplica.

    Solo aplica a obras que enviaron (cumplieron + tareo_incorrecto).
    Obras que NO enviaron solo reciben la notificacion de "NO ENVIO".
    """
    todas_enviaron = (
        resultado_cumplimiento["cumplieron"]
        + resultado_cumplimiento["tareo_incorrecto"]
    )

    # Filtrar solo las que tienen algun problema de formato o Drive
    obras_con_observacion = []
    for item in todas_enviaron:
        formato_ok = item.get("formato_ok", True)
        drive_ok = item.get("drive_ok", True)
        if not formato_ok or not drive_ok:
            obras_con_observacion.append(item)

    if not obras_con_observacion:
        print("[AGENTE 3] No hay observaciones de formato/Drive que notificar.")
        return []

    notificaciones_previas = _cargar_notificaciones()
    resultados = []
    fecha_str = fecha_objetivo.strftime("%d/%m/%Y")

    for item in obras_con_observacion:
        obra_key = item["obra_key"]
        obra_nombre = item["obra_nombre"]
        formato_ok = item.get("formato_ok", True)
        drive_ok = item.get("drive_ok", True)

        obra_info = OBRAS.get(obra_key, {})
        emails_destino = obra_info.get("emails", [])
        emails_cc = obra_info.get("emails_cc", [])

        # Verificar si ya se notifico (formato/drive) para esta obra y fecha
        noti_key = f"{obra_key}_{fecha_objetivo.isoformat()}_obs"
        if noti_key in notificaciones_previas:
            print(f"  [SKIP] {obra_nombre} - observaciones ya notificadas")
            resultados.append({
                "obra_key": obra_key,
                "obra_nombre": obra_nombre,
                "estado": "YA NOTIFICADA (obs)",
                "tipo": "formato_drive",
            })
            continue

        # Construir cuerpo del correo con las observaciones aplicables
        observaciones = []

        if not formato_ok:
            observaciones.append(
                "1. FORMATO DEL REPORTE:\n"
                "Se ha detectado que el reporte remitido no se encuentra alineado con el "
                "formato oficial establecido por la Empresa. En ese sentido, se solicita "
                "regularizarlo a la brevedad, adecuandolo estrictamente a las indicaciones "
                "proporcionadas, a fin de mantener el orden y la estandarizacion de los "
                "formatos preestablecidos."
            )

        if not drive_ok:
            num = len(observaciones) + 1
            observaciones.append(
                f"{num}. CARGA DE ARCHIVOS EN GOOGLE DRIVE:\n"
                "Se ha verificado que los archivos no estan siendo cargados en la carpeta "
                "correspondiente del Google Drive, incumpliendo la estructura de organizacion "
                "previamente establecida. En tal sentido, se solicita regularizar esta situacion "
                "a la mayor brevedad, asegurando que toda la documentacion sea almacenada en su "
                "ubicacion correcta conforme a los lineamientos definidos, con el proposito de "
                "garantizar el orden, la trazabilidad y el adecuado control de la informacion "
                "institucional."
            )

        asunto = f"[OBSERVACION] Tareo Diario - {obra_nombre} - {fecha_str}"

        cuerpo = f"""Estimados,

En relacion al Informe Diario de Personal de Obra (Tareo) correspondiente al dia {fecha_str}, se han identificado las siguientes observaciones para {obra_nombre}:

{chr(10).join(observaciones)}

Saludos cordiales,
Sistema Automatizado de Control y Gestion de Proyectos - HERGONSA
"""

        try:
            msg = MIMEText(cuerpo)
            if MODO_PRUEBA:
                msg["to"] = TEST_EMAIL
            else:
                msg["to"] = ", ".join(emails_destino)
                if emails_cc:
                    msg["cc"] = ", ".join(emails_cc)
            msg["from"] = mi_email
            msg["subject"] = asunto

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            sent = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            obs_tipo = []
            if not formato_ok:
                obs_tipo.append("formato")
            if not drive_ok:
                obs_tipo.append("drive")

            destino_info = TEST_EMAIL if MODO_PRUEBA else ", ".join(emails_destino)
            print(f"  [OK] Observacion ({'/'.join(obs_tipo)}) enviada a {obra_nombre}: {destino_info}")

            notificaciones_previas[noti_key] = {
                "obra": obra_nombre,
                "emails": emails_destino,
                "tipo": "formato_drive",
                "formato_ok": formato_ok,
                "drive_ok": drive_ok,
                "fecha_tareo": fecha_str,
                "enviado_el": datetime.now(PERU_TZ).isoformat(),
                "gmail_id": sent["id"],
            }

            resultados.append({
                "obra_key": obra_key,
                "obra_nombre": obra_nombre,
                "estado": "OBSERVACION ENVIADA",
                "tipo": "formato_drive",
                "formato_ok": formato_ok,
                "drive_ok": drive_ok,
                "gmail_id": sent["id"],
            })

        except Exception as e:
            print(f"  [ERROR] Fallo al enviar observacion a {obra_nombre}: {e}")
            resultados.append({
                "obra_key": obra_key,
                "obra_nombre": obra_nombre,
                "estado": f"ERROR: {e}",
                "tipo": "formato_drive",
            })

    _guardar_notificaciones(notificaciones_previas)
    return resultados
