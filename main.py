"""
ORQUESTADOR PRINCIPAL - Control Diario de Tareo de Obras
=========================================================
Ejecuta los 3 agentes en secuencia:
  1. Busqueda de correos de tareo
  2. Extraccion de datos de Excel (pestaña Resumen)
  3. Evaluacion de cumplimiento + notificacion a incumplidores
  4. Generacion y envio de reporte HTML

Uso:
  python main.py                       # Ejecutar todo (revisa tareo de ayer)
  python main.py --fecha 2026-02-21    # Revisar tareo de una fecha especifica
  python main.py --no-notificar        # Sin enviar llamados de atencion
  python main.py --solo-buscar         # Solo buscar y listar
"""
import argparse
import json
import os
import sys
import threading
from datetime import datetime, date, timedelta, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import REPORT_DIR, REPORT_JSON, REPORT_TXT, OBRAS, MODO_PRUEBA, TEST_EMAIL, COMPANY_COLUMN_LABEL
from auth_gmail import autenticar_gmail, autenticar_drive, obtener_perfil
from agente_busqueda_tareos import buscar_tareos
from agente_extractor_excel import extraer_datos_tareo
from agente_verificador_drive import verificar_subidas_drive
from agente_cumplimiento import evaluar_cumplimiento, enviar_notificaciones, enviar_notificaciones_adicionales
from enviar_reporte_tareos import enviar_reporte

# Zona horaria Peru (UTC-5)
PERU_TZ = timezone(timedelta(hours=-5))

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Control Diario de Tareo de Obras")
    parser.add_argument(
        "--fecha", type=str, default=None,
        help="Fecha del tareo a revisar (YYYY-MM-DD). Default: ayer"
    )
    parser.add_argument(
        "--no-notificar", action="store_true",
        help="No enviar correos de llamado de atencion"
    )
    parser.add_argument(
        "--solo-buscar", action="store_true",
        help="Solo buscar y listar correos (sin notificar ni reportar)"
    )
    args = parser.parse_args()

    # Determinar fecha objetivo
    if args.fecha:
        try:
            fecha_objetivo = datetime.strptime(args.fecha, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[bold red]Formato de fecha invalido: {args.fecha}. Usar YYYY-MM-DD[/bold red]")
            sys.exit(1)
    else:
        # Default: revisar el ultimo dia laboral
        # Lunes → revisa sabado (domingo no hay tareo)
        # Martes a sabado → revisa el dia anterior
        hoy = datetime.now(PERU_TZ).date()
        if hoy.weekday() == 0:  # Lunes
            fecha_objetivo = hoy - timedelta(days=2)  # Sabado
        elif hoy.weekday() == 6:  # Domingo (no deberia ejecutar, pero por si acaso)
            fecha_objetivo = hoy - timedelta(days=1)  # Sabado
        else:
            fecha_objetivo = hoy - timedelta(days=1)  # Ayer

    modo_txt = "[bold red][MODO PRUEBA][/bold red] " if MODO_PRUEBA else ""
    console.print(Panel.fit(
        f"{modo_txt}[bold cyan]CONTROL DIARIO DE TAREO - PERSONAL DE OBRA[/bold cyan]\n"
        f"Fecha del tareo: [bold]{fecha_objetivo.strftime('%d/%m/%Y')}[/bold]\n"
        f"Ejecucion: {datetime.now(PERU_TZ).strftime('%d/%m/%Y %H:%M')}",
        border_style="cyan",
    ))

    if MODO_PRUEBA:
        console.print(f"[bold red]  MODO PRUEBA: Todos los correos iran a {TEST_EMAIL}[/bold red]")

    # === AUTENTICACION ===
    console.print("\n[bold yellow]>>> AUTENTICACION[/bold yellow]")
    try:
        service = autenticar_gmail()
        mi_email = obtener_perfil(service)
        console.print(f"  Gmail conectado como: [green]{mi_email}[/green]")

        drive_service = autenticar_drive()
        console.print(f"  Drive conectado: [green]OK[/green]")
    except Exception as e:
        console.print(f"[bold red]Error de autenticacion: {e}[/bold red]")
        sys.exit(1)

    # === AGENTE 1: BUSQUEDA ===
    console.print("\n[bold yellow]>>> AGENTE 1: BUSQUEDA DE CORREOS DE TAREO[/bold yellow]")
    tareos = buscar_tareos(service, fecha_objetivo)

    console.print(f"\n  Obras monitoreadas: [bold]{len(OBRAS)}[/bold]")
    console.print(f"  Correos de tareo encontrados: [bold]{len(tareos)}[/bold]")

    if tareos:
        _mostrar_tabla_tareos(tareos)

    # === AGENTE 2: EXTRACCION DE DATOS ===
    console.print("\n[bold yellow]>>> AGENTE 2: EXTRACCION DE DATOS DE EXCEL[/bold yellow]")

    for i, tareo in enumerate(tareos):
        console.print(f"  [{i+1}/{len(tareos)}] {tareo['obra_nombre']}...", end=" ")

        if not tareo["tiene_adjunto_excel"]:
            tareo["datos_excel"] = {"error": "Sin adjunto Excel"}
            console.print("[yellow]SIN ADJUNTO[/yellow]")
            continue

        try:
            # Usar timeout de 30 segundos por archivo
            resultado_datos = [None]
            error_datos = [None]

            def _extraer():
                try:
                    resultado_datos[0] = extraer_datos_tareo(
                        service, tareo["id"], tareo["adjuntos"], fecha_objetivo
                    )
                except Exception as ex:
                    error_datos[0] = ex

            hilo = threading.Thread(target=_extraer)
            hilo.daemon = True
            hilo.start()
            hilo.join(timeout=30)

            if hilo.is_alive():
                tareo["datos_excel"] = {"error": "Timeout (>30s)"}
                console.print("[yellow]TIMEOUT[/yellow]")
                continue

            if error_datos[0]:
                raise error_datos[0]

            datos = resultado_datos[0]
            tareo["datos_excel"] = datos or {}

            if datos and datos.get("total_obreros", 0) > 0:
                console.print(
                    f"[green]OK[/green] "
                    f"(Fecha: {datos.get('fecha_tareo', '-')}, "
                    f"H:{datos.get('personal_empresa', 0)}, "
                    f"S:{datos.get('personal_sindicato', 0)}, "
                    f"T:{datos.get('total_obreros', 0)}, "
                    f"Staff:{datos.get('personal_staff', 0)})"
                )
            else:
                console.print(f"[yellow]PARCIAL[/yellow] ({datos.get('error', 'Sin datos')})")

        except Exception as e:
            tareo["datos_excel"] = {"error": str(e)}
            console.print(f"[red]ERROR[/red] ({e})")

    if args.solo_buscar:
        _guardar_reporte_parcial(tareos, fecha_objetivo, mi_email)
        console.print("\n[green]Busqueda completada. Ejecuta sin --solo-buscar para el flujo completo.[/green]")
        return

    # === AGENTE 3.5: VERIFICACION GOOGLE DRIVE ===
    console.print("\n[bold yellow]>>> AGENTE 3.5: VERIFICACION DE SUBIDAS A GOOGLE DRIVE[/bold yellow]")

    try:
        resultados_drive = verificar_subidas_drive(drive_service, fecha_objetivo)
        total_drive_ok = sum(1 for v in resultados_drive.values() if v.get("subido"))
        console.print(f"\n  Subidas verificadas: [bold]{total_drive_ok}/{len(resultados_drive)}[/bold] obras con archivos en Drive")
    except Exception as e:
        console.print(f"[red]  Error verificando Drive: {e}[/red]")
        resultados_drive = {}

    # === AGENTE 3: CUMPLIMIENTO Y NOTIFICACION ===
    console.print("\n[bold yellow]>>> AGENTE 3: EVALUACION DE CUMPLIMIENTO[/bold yellow]")

    resultado_cumplimiento = evaluar_cumplimiento(tareos, fecha_objetivo, resultados_drive)

    _mostrar_tabla_cumplimiento(resultado_cumplimiento)

    # Enviar notificaciones a obras incumplidoras
    resultado_notificaciones = []
    resultado_notificaciones_obs = []

    if resultado_cumplimiento["no_enviaron"]:
        if args.no_notificar:
            console.print("\n[yellow]  Notificaciones desactivadas (--no-notificar)[/yellow]")
        else:
            console.print("\n[bold yellow]>>> ENVIANDO NOTIFICACIONES DE LLAMADO DE ATENCION[/bold yellow]")
            resultado_notificaciones = enviar_notificaciones(
                service, resultado_cumplimiento["no_enviaron"], fecha_objetivo, mi_email
            )
    else:
        console.print("\n[green]  Todas las obras cumplieron! No hay notificaciones de NO ENVIO.[/green]")

    # Enviar notificaciones adicionales (formato/Drive)
    if not args.no_notificar:
        console.print("\n[bold yellow]>>> ENVIANDO OBSERVACIONES (FORMATO / DRIVE)[/bold yellow]")
        resultado_notificaciones_obs = enviar_notificaciones_adicionales(
            service, resultado_cumplimiento, fecha_objetivo, mi_email
        )
    else:
        console.print("\n[yellow]  Observaciones de formato/Drive desactivadas (--no-notificar)[/yellow]")

    # === REPORTE ===
    console.print("\n[bold yellow]>>> GENERANDO Y ENVIANDO REPORTE[/bold yellow]")

    enviar_reporte(service, mi_email, resultado_cumplimiento, resultado_notificaciones)

    # Guardar reportes locales
    _guardar_reporte_completo(resultado_cumplimiento, resultado_notificaciones, mi_email)

    # Resumen final
    cum = resultado_cumplimiento
    total_noti = len(resultado_notificaciones) + len(resultado_notificaciones_obs)
    console.print(Panel.fit(
        "[bold green]PROCESO COMPLETADO[/bold green]\n"
        f"{'[MODO PRUEBA] ' if MODO_PRUEBA else ''}"
        f"Fecha del tareo: {cum['fecha_objetivo']}\n"
        f"Cumplieron: {len(cum['cumplieron'])}/{cum['total_obras']}\n"
        f"Fecha incorrecta: {len(cum['tareo_incorrecto'])}\n"
        f"No enviaron: {len(cum['no_enviaron'])}\n"
        f"Notificaciones enviadas: {total_noti} (llamados: {len(resultado_notificaciones)}, observaciones: {len(resultado_notificaciones_obs)})\n"
        f"Reporte guardado en: {REPORT_DIR}",
        border_style="green",
    ))


def _mostrar_tabla_tareos(tareos):
    """Muestra tabla de correos de tareo encontrados."""
    table = Table(title="CORREOS DE TAREO ENCONTRADOS", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Obra", style="bold white", max_width=20)
    table.add_column("Remitente", style="yellow", max_width=35)
    table.add_column("Fecha Envio", style="white", width=16)
    table.add_column("Asunto", max_width=40)
    table.add_column("Excel", style="white", width=6)

    for i, tareo in enumerate(tareos, 1):
        excel_status = "[green]SI[/green]" if tareo["tiene_adjunto_excel"] else "[red]NO[/red]"
        table.add_row(
            str(i),
            tareo["obra_nombre"],
            tareo["de_email"],
            tareo["fecha_envio"][:16] if tareo["fecha_envio"] else "-",
            tareo["asunto"][:40],
            excel_status,
        )

    console.print(table)


def _mostrar_tabla_cumplimiento(resultado):
    """Muestra tabla resumen de cumplimiento."""
    table = Table(title="RESUMEN DE CUMPLIMIENTO", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Obra", style="bold white", max_width=20)
    table.add_column("Estado", width=18)
    table.add_column("Fecha Tareo", width=12)
    table.add_column(COMPANY_COLUMN_LABEL or "EMPRESA", style="white", width=10)
    table.add_column("SINDICATO", style="white", width=10)
    table.add_column("TOTAL Ob.", style="white", width=10)
    table.add_column("STAFF", style="white", width=8)
    table.add_column("Formato", width=8)
    table.add_column("G.Drive", width=8)

    i = 0

    for item in resultado["cumplieron"]:
        i += 1
        datos = item.get("datos", {})
        fmt_ok = "[green]Ok[/green]" if item.get("formato_ok") else "[red]Corregir[/red]"
        drv_ok = "[green]Ok[/green]" if item.get("drive_ok") else "[red]Falta[/red]"
        table.add_row(
            str(i),
            item["obra_nombre"],
            f"[green]{item['estado']}[/green]",
            datos.get("fecha_tareo", "-"),
            str(datos.get("personal_empresa", 0)),
            str(datos.get("personal_sindicato", 0)),
            str(datos.get("total_obreros", 0)),
            str(datos.get("personal_staff", 0)),
            fmt_ok,
            drv_ok,
        )

    for item in resultado["tareo_incorrecto"]:
        i += 1
        datos = item.get("datos", {})
        fmt_ok = "[green]Ok[/green]" if item.get("formato_ok") else "[red]Corregir[/red]"
        drv_ok = "[green]Ok[/green]" if item.get("drive_ok") else "[red]Falta[/red]"
        table.add_row(
            str(i),
            item["obra_nombre"],
            f"[yellow]{item['estado']}[/yellow]",
            datos.get("fecha_tareo", "-"),
            str(datos.get("personal_empresa", 0)),
            str(datos.get("personal_sindicato", 0)),
            str(datos.get("total_obreros", 0)),
            str(datos.get("personal_staff", 0)),
            fmt_ok,
            drv_ok,
        )

    for item in resultado["no_enviaron"]:
        i += 1
        drv_ok = "[green]Ok[/green]" if item.get("drive_ok") else "[red]Falta[/red]"
        table.add_row(
            str(i),
            item["obra_nombre"],
            f"[red]{item['estado']}[/red]",
            "-", "-", "-", "-", "-",
            "-",
            drv_ok,
        )

    console.print(table)


def _guardar_reporte_completo(resultado_cumplimiento, resultado_notificaciones, mi_email):
    """Guarda los resultados en archivos JSON y TXT."""
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Serializar datos para JSON
    def _serializar(item):
        """Convierte un item de cumplimiento a formato serializable."""
        copia = dict(item)
        # Limpiar campos no serializables del tareo
        if "tareo" in copia:
            tareo = dict(copia["tareo"])
            tareo.pop("adjuntos", None)
            copia["tareo"] = tareo
        return copia

    data = {
        "fecha_ejecucion": datetime.now(PERU_TZ).isoformat(),
        "usuario": mi_email,
        "fecha_objetivo": resultado_cumplimiento["fecha_objetivo"],
        "total_obras": resultado_cumplimiento["total_obras"],
        "cumplieron": [_serializar(c) for c in resultado_cumplimiento["cumplieron"]],
        "tareo_incorrecto": [_serializar(c) for c in resultado_cumplimiento["tareo_incorrecto"]],
        "no_enviaron": resultado_cumplimiento["no_enviaron"],
        "notificaciones": resultado_notificaciones,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Reporte TXT
    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("CONTROL DIARIO DE TAREO - PERSONAL DE OBRA\n")
        f.write(f"Fecha del tareo: {resultado_cumplimiento['fecha_objetivo']}\n")
        f.write(f"Ejecucion: {datetime.now(PERU_TZ).strftime('%d/%m/%Y %H:%M')}\n")
        f.write(f"Usuario: {mi_email}\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Total obras monitoreadas: {resultado_cumplimiento['total_obras']}\n")
        f.write(f"Cumplieron: {len(resultado_cumplimiento['cumplieron'])}\n")
        f.write(f"Fecha incorrecta: {len(resultado_cumplimiento['tareo_incorrecto'])}\n")
        f.write(f"No enviaron: {len(resultado_cumplimiento['no_enviaron'])}\n\n")

        f.write("--- OBRAS QUE CUMPLIERON ---\n")
        for item in resultado_cumplimiento["cumplieron"]:
            datos = item.get("datos", {})
            f.write(f"  {item['obra_nombre']} - {item['estado']}\n")
            f.write(f"    Fecha tareo: {datos.get('fecha_tareo', '-')}\n")
            f.write(f"    {COMPANY_COLUMN_LABEL or 'EMPRESA'}: {datos.get('personal_empresa', 0)}\n")
            f.write(f"    SINDICATO: {datos.get('personal_sindicato', 0)}\n")
            f.write(f"    TOTAL Obreros: {datos.get('total_obreros', 0)}\n")
            f.write(f"    STAFF: {datos.get('personal_staff', 0)}\n\n")

        if resultado_cumplimiento["tareo_incorrecto"]:
            f.write("--- OBRAS CON FECHA INCORRECTA ---\n")
            for item in resultado_cumplimiento["tareo_incorrecto"]:
                f.write(f"  {item['obra_nombre']} - {item.get('detalle', '')}\n\n")

        if resultado_cumplimiento["no_enviaron"]:
            f.write("--- OBRAS QUE NO ENVIARON ---\n")
            for item in resultado_cumplimiento["no_enviaron"]:
                f.write(f"  {item['obra_nombre']}\n")
                f.write(f"    Emails: {', '.join(item['emails_registrados'])}\n\n")

    console.print(f"\n[dim]Reportes guardados:[/dim]")
    console.print(f"  [dim]JSON: {REPORT_JSON}[/dim]")
    console.print(f"  [dim]TXT:  {REPORT_TXT}[/dim]")


def _guardar_reporte_parcial(tareos, fecha_objetivo, mi_email):
    """Guarda reporte parcial (solo busqueda)."""
    os.makedirs(REPORT_DIR, exist_ok=True)

    data = {
        "fecha_ejecucion": datetime.now(PERU_TZ).isoformat(),
        "usuario": mi_email,
        "fecha_objetivo": fecha_objetivo.strftime("%d/%m/%Y"),
        "modo": "solo-buscar",
        "correos_encontrados": len(tareos),
        "tareos": [
            {
                "obra": t["obra_nombre"],
                "de_email": t["de_email"],
                "asunto": t["asunto"],
                "fecha_envio": t["fecha_envio"],
                "tiene_excel": t["tiene_adjunto_excel"],
            }
            for t in tareos
        ],
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
