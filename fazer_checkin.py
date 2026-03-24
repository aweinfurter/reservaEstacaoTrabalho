"""
fazer_checkin.py
================
Script independente para realizar o check-in de uma reserva DeskBee/TOTVS.

Uso:
    python3 fazer_checkin.py

O código de check-in é lido do config.cfg (campo checkin_code).
"""

import os, sys
# Se não estiver rodando dentro do .venv, relança com o Python do venv
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENV_PYTHON = os.path.join(
    _HERE, ".venv",
    "Scripts" if sys.platform == "win32" else "bin",
    "python.exe" if sys.platform == "win32" else "python",
)
if os.path.exists(_VENV_PYTHON) and os.path.abspath(sys.executable) != os.path.abspath(_VENV_PYTHON):
    import subprocess
    sys.exit(subprocess.call([_VENV_PYTHON] + sys.argv))

import traceback

from reservar_estacao import (
    CHECKIN_CODE,
    setup_driver,
    handle_sso_login,
    do_checkin,
)


def main():
    print("=" * 55)
    print(" Automação de Check-in — DeskBee / TOTVS")
    print("=" * 55)
    print(f" Código : {CHECKIN_CODE}")
    print("=" * 55)

    if not CHECKIN_CODE:
        print("\n[ERRO] checkin_code não definido no config.cfg.")
        print("  Preencha o campo 'checkin_code' na seção [reserva].")
        return

    driver = setup_driver()

    try:
        do_checkin(driver, CHECKIN_CODE)
    except Exception:
        print("\n[ERRO] Ocorreu um problema durante o check-in:")
        traceback.print_exc()
    finally:
        input("\nPressione ENTER para fechar o browser...")
        driver.quit()


if __name__ == "__main__":
    main()
