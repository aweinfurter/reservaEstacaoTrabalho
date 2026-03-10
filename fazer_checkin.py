"""
fazer_checkin.py
================
Script independente para realizar o check-in de uma reserva DeskBee/TOTVS.

Uso:
    python3 fazer_checkin.py

O código de check-in é lido do config.cfg (campo checkin_code).
"""

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
