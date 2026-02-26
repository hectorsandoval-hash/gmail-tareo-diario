"""
Configuracion de Windows Task Scheduler para Control de Tareo Diario.
Programa la ejecucion diaria a las 7:00 AM.
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASK_NAME = "ControlTareoDiario_7AM"


def crear_tarea():
    """Crea la tarea programada en Windows Task Scheduler."""
    bat_path = os.path.join(BASE_DIR, "ejecutar_reporte.bat")

    if not os.path.exists(bat_path):
        print(f"[ERROR] No se encontro: {bat_path}")
        sys.exit(1)

    # Crear directorio de logs
    logs_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Eliminar tarea existente si hay
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True,
    )

    # Crear nueva tarea: diaria a las 7:00 AM
    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{bat_path}"',
        "/sc", "daily",
        "/st", "07:00",
        "/rl", "HIGHEST",
        "/f",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"[OK] Tarea '{TASK_NAME}' creada exitosamente.")
        print(f"  Horario: Diariamente a las 07:00 AM")
        print(f"  Archivo: {bat_path}")
        print(f"  Logs:    {logs_dir}")
    else:
        print(f"[ERROR] No se pudo crear la tarea:")
        print(f"  {result.stderr}")
        print("\nIntenta ejecutar como Administrador.")


def verificar_tarea():
    """Verifica si la tarea existe."""
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print(f"[OK] Tarea '{TASK_NAME}' encontrada:")
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and ":" in line:
                print(f"  {line}")
    else:
        print(f"[WARN] Tarea '{TASK_NAME}' no encontrada.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--verificar":
        verificar_tarea()
    else:
        crear_tarea()
