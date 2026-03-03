import os
import shutil
import time
import traceback
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURAÇÕES - Edite aqui conforme necessário
# ============================================================

# Data calculada automaticamente a partir da última reserva (próxima segunda-feira)
# Pode sobrescrever manualmente se necessário:
TARGET_DAY   = None
TARGET_MONTH = None
TARGET_YEAR  = None

START_TIME = "0800"    # Horário de início (formato hhmm)
END_TIME   = "1800"    # Horário de fim    (formato hhmm)

BUILDING    = "Joinville › Santa Catarina - Bloco B"
FLOOR       = "3º Andar"
WORKSTATION = "B063"

# Perfil original do Chrome — onde está a sessão SSO salva.
CHROME_PROFILE_DIR = os.path.expanduser("~/.config/google-chrome")
CHROME_PROFILE     = "Default"

# Pasta temporária: o script copia os arquivos de sessão para cá
# e inicia um Chrome separado, sem conflitar com o Chrome aberto.
CHROME_TEMP_DIR    = "/tmp/chrome-deskbee-profile"

REMOTE_DEBUG_PORT  = None

# ============================================================

MONTH_NAMES_PT = {
    1: "Janeiro",  2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",     6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro", 10: "Outubro",  11: "Novembro", 12: "Dezembro",
}


# ── Helpers ─────────────────────────────────────────────────

def copy_session(src_profile_dir: str, src_profile: str, dest_dir: str):
    """
    Copia os arquivos de sessão/cookies do perfil original para uma pasta
    temporária, permitindo que o Selenium inicie um Chrome separado já logado.
    """
    src  = os.path.join(src_profile_dir, src_profile)
    dest = os.path.join(dest_dir, "Default")

    # Arquivos/pastas que carregam a sessão SSO
    items = [
        "Cookies",
        "Login Data",
        "Login Data For Account",
        "Preferences",
        "Secure Preferences",
        "Network",         # contém Cookies em Chrome mais recente
        "Local Storage",
        "Session Storage",
        "IndexedDB",
        "Web Data",
    ]

    os.makedirs(dest, exist_ok=True)

    # Copia Local State (fica no nível do perfil, não dentro de Default)
    local_state_src = os.path.join(src_profile_dir, "Local State")
    if os.path.exists(local_state_src):
        shutil.copy2(local_state_src, os.path.join(dest_dir, "Local State"))

    for item in items:
        s = os.path.join(src, item)
        d = os.path.join(dest, item)
        if not os.path.exists(s):
            continue
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)

    # Remove lock files para evitar conflito
    for lock in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lf = os.path.join(dest, lock)
        if os.path.exists(lf):
            os.remove(lf)

    print(f"  → Sessão copiada para {dest_dir}")


def setup_driver() -> webdriver.Chrome:
    print("  → Copiando sessão SSO do Chrome...")
    copy_session(CHROME_PROFILE_DIR, CHROME_PROFILE, CHROME_TEMP_DIR)

    options = Options()
    options.add_argument(f"--user-data-dir={CHROME_TEMP_DIR}")
    options.add_argument(f"--profile-directory=Default")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    print("  → Iniciando Chrome com sessão copiada...")
    return webdriver.Chrome(options=options)


def scroll_and_click(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.3)
    element.click()


def wait_click(driver, by, selector, timeout=15):
    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, selector))
    )
    scroll_and_click(driver, el)
    return el


# ── Calendário ───────────────────────────────────────────────

def navigate_calendar(driver, target_month: int, target_year: int):
    """Navega o calendário para o mês/ano desejado."""
    target_name = MONTH_NAMES_PT[target_month]

    for _ in range(30):
        # Lê mês e ano exibidos
        month_spans = driver.find_elements(
            By.CSS_SELECTOR,
            ".q-date__navigation .relative-position button span.block"
        )
        if len(month_spans) < 2:
            time.sleep(0.5)
            continue

        cur_month_text = month_spans[0].text.strip()
        cur_year_text  = month_spans[1].text.strip()

        if cur_month_text == target_name and cur_year_text == str(target_year):
            return

        cur_month_num = next(
            (k for k, v in MONTH_NAMES_PT.items() if v == cur_month_text), 1
        )
        cur_year_num = int(cur_year_text) if cur_year_text.isdigit() else target_year

        if (cur_year_num * 12 + cur_month_num) < (target_year * 12 + target_month):
            driver.find_element(By.CSS_SELECTOR, "button[aria-label='Next month']").click()
        else:
            driver.find_element(By.CSS_SELECTOR, "button[aria-label='Previous month']").click()

        time.sleep(0.5)

    raise Exception(f"Não foi possível navegar até {target_month}/{target_year} no calendário.")


def select_calendar_day(driver, day: int):
    """Clica no botão do dia dentro do calendário."""
    day_spans = driver.find_elements(
        By.CSS_SELECTOR,
        ".q-date__calendar-item--in button .q-btn__content span.block"
    )
    for span in day_spans:
        if span.text.strip() == str(day):
            # Sobe dois níveis: span.block → .q-btn__content → button
            btn = span.find_element(By.XPATH, "../..")
            btn.click()
            return
    raise Exception(f"Dia {day} não encontrado no calendário.")


# ── Inputs ───────────────────────────────────────────────────

def fill_time_input(driver, data_bee: str, value: str):
    """Preenche um input de horário via atributo data-bee."""
    el = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, f"input[data-bee='{data_bee}']"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    driver.execute_script("arguments[0].click();", el)
    time.sleep(0.2)
    # Limpa e digita via JS para garantir o preenchimento
    driver.execute_script(
        "arguments[0].value = ''; arguments[0].dispatchEvent(new Event('input'));", el
    )
    el.send_keys(value)
    # Dispara eventos para o framework Vue/Quasar reconhecer o valor
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input')); "
        "arguments[0].dispatchEvent(new Event('change'));",
        el,
    )
    time.sleep(0.3)


def select_dropdown_option(driver, input_data_bee: str, option_text: str):
    """Abre o dropdown via data-bee e clica diretamente no span com o texto."""
    input_el = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, f"input[data-bee='{input_data_bee}']"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", input_el)
    input_el.click()

    # Usa a parte mais única/final do texto para evitar problemas com caracteres especiais (›)
    unique_part = option_text.split("›")[-1].strip() if "›" in option_text else option_text

    # Tenta match pelo trecho único — mais rápido e sem problema com encoding
    xpaths = [
        f"//span[contains(@class,'ellipsis') and contains(normalize-space(text()),'{unique_part}')]",
        f"//*[contains(@class,'q-item') and contains(normalize-space(.),'{unique_part}')]",
    ]

    option = None
    for xp in xpaths:
        try:
            option = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            break
        except Exception:
            continue

    if option is None:
        raise Exception(f"Opção '{option_text}' não encontrada no dropdown de '{input_data_bee}'.")

    try:
        option.click()
    except Exception:
        driver.execute_script("arguments[0].click();", option)


# ── Recorrência ─────────────────────────────────────────────

def fill_number_input(driver, data_bee: str, value):
    """Preenche um input numérico via atributo data-bee."""
    el = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, f"input[data-bee='{data_bee}']"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    driver.execute_script("arguments[0].click();", el)
    time.sleep(0.2)
    driver.execute_script(
        "arguments[0].value = ''; arguments[0].dispatchEvent(new Event('input'));", el
    )
    el.send_keys(str(value))
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input')); "
        "arguments[0].dispatchEvent(new Event('change'));",
        el,
    )
    time.sleep(0.3)


def select_weekdays(driver, days: list):
    """Clica nos botões dos dias da semana (ex: ['SEG', 'TER'])."""
    for day in days:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH,
                f"//button[.//span[contains(@class,'h-text__body-2') and normalize-space(text())='{day}']]"
            ))
        )
        scroll_and_click(driver, btn)


# ── Estação & Confirmação ─────────────────────────────────────

def click_lista_view(driver):
    """Clica no botão 'Lista' para exibir a listagem de estações."""
    btn = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//button[.//span[contains(@class,'components__atom__button__label--space__icon')]//span[normalize-space(text())='Lista']]"
        ))
    )
    scroll_and_click(driver, btn)
    # Aguarda ao menos um item da lista carregar
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "span[data-bee='booking.item.display_name']"))
    )


def select_workstation(driver, name: str):
    """Abre a view de lista e clica em 'Selecionar' na estação que contém o nome/código."""
    # Aguarda ao menos um item da lista aparecer
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((
            By.CSS_SELECTOR,
            "span[data-bee='booking.item.display_name']"
        ))
    )
    # Botão "Selecionar" dentro do wrapper que contém o nome da estação
    xpath = (
        f"//span[@data-bee='booking.item.display_name' and contains(normalize-space(text()),'{name}')]"
        "/ancestor::div[contains(@class,'components__system__workspace__item__wrapper-info')]"
        "//button[@data-bee='booking.item.select']"
    )
    btn = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    scroll_and_click(driver, btn)
    time.sleep(0.6)


def confirm_reservation(driver):
    """Clica no botão de confirmar/salvar a reserva."""
    candidates = [
        "//button[.//span[contains(normalize-space(text()),'Confirmar')]]",
        "//button[.//span[contains(normalize-space(text()),'Reservar')]]",
        "//button[.//span[contains(normalize-space(text()),'Salvar')]]",
        "//button[.//span[contains(normalize-space(text()),'Finalizar')]]",
        "//button[.//span[contains(normalize-space(text()),'Concluir')]]",
    ]
    for xpath in candidates:
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            scroll_and_click(driver, btn)
            print("✔  Reserva confirmada com sucesso!")
            return
        except Exception:
            continue

    print("⚠  Botão de confirmação não encontrado automaticamente. Confirme manualmente.")


# ── Data automática ──────────────────────────────────────────

def next_monday_after(date: datetime) -> datetime:
    """Retorna a próxima segunda-feira após a data informada."""
    days_ahead = 0 - date.weekday()  # 0 = segunda
    if days_ahead <= 0:
        days_ahead += 7
    return date + timedelta(days=days_ahead)


def get_last_reservation_date(driver) -> datetime:
    """Acessa diretamente a página de reservas, lê todas as datas e retorna a mais recente."""
    print("\n[→] Acessando 'Minhas reservas'...")
    driver.get("https://totvs.deskbee.app/app/booking/my")

    # Aguarda ao menos um card de reserva carregar
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-bee='my-bookings.item.datetime']"))
    )

    # Lê todas as datas exibidas — formato: "31/03/2026 - 08:00 às 18:00"
    elements = driver.find_elements(By.CSS_SELECTOR, "[data-bee='my-bookings.item.datetime']")
    dates = []
    for el in elements:
        text = el.text.strip().split(" - ")[0]  # pega só "31/03/2026"
        try:
            dates.append(datetime.strptime(text, "%d/%m/%Y"))
        except ValueError:
            continue

    if not dates:
        raise Exception("Nenhuma reserva encontrada em 'Minhas reservas'.")

    last_date = max(dates)
    print(f"[→] Última reserva encontrada: {last_date.strftime('%d/%m/%Y')}")
    return last_date


# ── Fluxo principal ──────────────────────────────────────────

def main():
    global TARGET_DAY, TARGET_MONTH, TARGET_YEAR

    print("=" * 55)
    print(" Automação de Reserva — DeskBee / TOTVS")
    print("=" * 55)
    print(f" Horário     : {START_TIME} – {END_TIME}")
    print(f" Prédio      : {BUILDING}")
    print(f" Andar       : {FLOOR}")
    print(f" Estação     : {WORKSTATION}")
    print("=" * 55)

    driver = setup_driver()

    try:
        # 1. Lê última reserva e calcula próxima segunda-feira
        if TARGET_DAY is None:
            last_date   = get_last_reservation_date(driver)
            next_monday = next_monday_after(last_date)
            TARGET_DAY   = next_monday.day
            TARGET_MONTH = next_monday.month
            TARGET_YEAR  = next_monday.year
            print(f"[→] Próxima segunda-feira: {next_monday.strftime('%d/%m/%Y')}")

        print(f"\n Data calculada : {TARGET_DAY:02d}/{TARGET_MONTH:02d}/{TARGET_YEAR}")
        print("=" * 55)

        # 2. Vai para a página inicial
        print("\n[2/14] Acessando a página inicial...")
        driver.get("https://totvs.deskbee.app/app/home")
        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//span[contains(@class,'components__atom__button__label--space__icon')]"
                "//span[normalize-space(text())='Reserva Estação']"
            ))
        )

        # 3. Botão "Reserva Estação"
        print("[3/14] Clicando em 'Reserva Estação'...")
        wait_click(
            driver, By.XPATH,
            "//span[contains(@class,'components__atom__button__label--space__icon')]"
            "//span[normalize-space(text())='Reserva Estação']"
        )

        # 4. Abrir calendário — aguarda o input de data estar clicável
        print("[4/14] Abrindo calendário...")
        date_input = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[data-bee='booking.workspace.date']")
            )
        )
        scroll_and_click(driver, date_input)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".q-date__calendar-days"))
        )

        # 5. Navegar e selecionar o dia
        print(f"[5/14] Selecionando {TARGET_DAY}/{TARGET_MONTH}/{TARGET_YEAR}...")
        navigate_calendar(driver, TARGET_MONTH, TARGET_YEAR)
        select_calendar_day(driver, TARGET_DAY)
        WebDriverWait(driver, 5).until(
            lambda d: d.find_element(By.CSS_SELECTOR, "input[data-bee='booking.workspace.date']").get_attribute("value") != ""
        )

        # 5. Horário de início
        print(f"[6/14] Horário de início: {START_TIME}...")
        fill_time_input(driver, "booking.workspace.start_hour", START_TIME)

        # 6. Horário de fim
        print(f"[7/14] Horário de fim: {END_TIME}...")
        fill_time_input(driver, "booking.workspace.end_hour", END_TIME)

        # 7. Unidade / Prédio
        print(f"[8/14] Selecionando prédio: {BUILDING}...")
        select_dropdown_option(driver, "booking.workspace.building", BUILDING)

        # 8. Andar
        print(f"[9/14] Selecionando andar: {FLOOR}...")
        select_dropdown_option(driver, "booking.workspace.floor", FLOOR)

        # 9. Recorrência
        print("[10/14] Selecionando recorrência: Semanal...")
        select_dropdown_option(driver, "booking.workspace.recurrency_type", "Semanal")

        # 10. Quantidade de repetições
        print("[11/14] Definindo repetições: 4 semanas...")
        fill_number_input(driver, "booking.workspace.recurrency_times", 4)

        # 11. Dias da semana
        print("[12/14] Selecionando dias: SEG e TER...")
        select_weekdays(driver, ["SEG", "TER"])

        # 12. Alternar para view de lista
        print("[13/14] Clicando em 'Lista'...")
        click_lista_view(driver)

        # 13. Estação  ← COMENTADO PARA TESTES
        # print(f"[14/14] Selecionando estação: {WORKSTATION}...")
        # select_workstation(driver, WORKSTATION)
        # time.sleep(1)

        # 14. Confirmar  ← COMENTADO PARA TESTES
        # print("\n[14/14] Confirmando a reserva...")
        # confirm_reservation(driver)
        # time.sleep(3)

        print("\nProcesso concluído! (confirmação desabilitada para teste)")

    except Exception:
        print("\n[ERRO] Ocorreu um problema durante a automação:")
        traceback.print_exc()

    finally:
        input("\nPressione ENTER para fechar o browser...")
        driver.quit()


if __name__ == "__main__":
    main()
