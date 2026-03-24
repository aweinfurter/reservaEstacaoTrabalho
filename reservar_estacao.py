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

import configparser
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

from sso_login import handle_sso_login

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

# Lê as variáveis sensíveis do arquivo config.cfg (não commitado no git)
# interpolation=None evita erros quando a senha contém o caractere '%'
_cfg = configparser.ConfigParser(interpolation=None)
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.cfg")
if not os.path.exists(_cfg_path):
    raise FileNotFoundError(
        f"Arquivo de configuração não encontrado: {_cfg_path}\n"
        "Copie o config.cfg.example e preencha com seus dados."
    )
_cfg.read(_cfg_path, encoding="utf-8")

BUILDING      = _cfg.get("reserva", "building")
FLOOR         = _cfg.get("reserva", "floor")
WORKSTATION   = _cfg.get("reserva", "workstation")
CHECKIN_CODE  = _cfg.get("reserva", "checkin_code", fallback="")
LOGIN         = _cfg.get("auth", "login", fallback="")
SENHA         = _cfg.get("auth", "senha", fallback="")

# Perfil original do Chrome — onde está a sessão SSO salva.
# Detecta automaticamente o caminho correto em cada sistema operacional.
import platform as _platform
_sys = _platform.system()
if _sys == "Windows":
    CHROME_PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
elif _sys == "Darwin":  # macOS
    CHROME_PROFILE_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
else:  # Linux
    CHROME_PROFILE_DIR = os.path.expanduser("~/.config/google-chrome")

CHROME_PROFILE = "Default"

# Pasta temporária para a sessão copiada
if _sys == "Windows":
    CHROME_TEMP_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "chrome-deskbee-profile")
else:
    CHROME_TEMP_DIR = "/tmp/chrome-deskbee-profile"

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
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    # Modo headless: sem janela visível, imune a minimizar/focar
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    print("  → Iniciando Chrome headless com sessão copiada...")
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
            btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Next month']")
        else:
            btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Previous month']")

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        driver.execute_script("arguments[0].click();", btn)

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
    _LISTA_XPATHS = [
        # Seletor original
        "//button[.//span[contains(@class,'components__atom__button__label--space__icon')]//span[normalize-space(text())='Lista']]",
        # Qualquer botão cujo texto visível seja 'Lista'
        "//button[.//span[normalize-space(text())='Lista']]",
        "//button[normalize-space(.)='Lista']",
    ]
    btn = None
    for xpath in _LISTA_XPATHS:
        try:
            btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            break
        except Exception:
            continue
    if btn is None:
        raise Exception("Botão 'Lista' não encontrado. Verifique o seletor em click_lista_view().")
    scroll_and_click(driver, btn)

    # Seletores de notificação/toast de erro do Quasar
    _ERRO_NOTIF_CSS = ", ".join([
        ".q-notification",
        ".q-banner",
        "[class*='notification']",
        "[class*='alert']",
        "[class*='error']",
    ])
    _FRASES_ERRO = [
        "limite máximo",
        "30 dias",
        "precondition",
        "regra",
        "booking_rule",
        "não é possível",
        "não permitido",
    ]

    def _lista_ou_erro(d):
        # Lista carregou
        if d.find_elements(By.CSS_SELECTOR, "span[data-bee='booking.item.display_name']"):
            return "ok"
        # Notificação de erro visível
        for el in d.find_elements(By.CSS_SELECTOR, _ERRO_NOTIF_CSS):
            texto = el.text.lower()
            if any(f in texto for f in _FRASES_ERRO):
                return f"erro: {el.text.strip()}"
        return None

    try:
        resultado = WebDriverWait(driver, 15).until(_lista_ou_erro)
    except Exception:
        resultado = None

    if resultado == "ok":
        return
    elif resultado and resultado.startswith("erro:"):
        raise Exception(f"Reserva bloqueada pela plataforma: {resultado[5:].strip()}")
    else:
        # Timeout sem lista e sem notificação — verifica se há algo visível na página
        msgs = driver.find_elements(By.CSS_SELECTOR, _ERRO_NOTIF_CSS)
        for el in msgs:
            if el.text.strip():
                raise Exception(f"Reserva bloqueada pela plataforma: {el.text.strip()}")
        raise Exception(
            "Lista de estações não carregou após 15s. Pode ser limite de antecedência (30 dias) "
            "ou outro bloqueio da plataforma."
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


# ── Check-in ─────────────────────────────────────────────────

_XPATH_CHECKIN_ATIVO = (
    "//button[contains(@class,'booking-my-button-checkin')"
    " and not(contains(@class,'booking-my-button-checkin-disable'))"
    " and not(@disabled)"
    " and .//span[normalize-space(text())='checkin']]"
)

_CHECKIN_INPUT_SELECTORS = [
    "input[data-bee='checkin.code']",
    "input[data-bee='booking.checkin.code']",
    "input[data-bee='my-bookings.checkin.code']",
    ".q-dialog input[type='text']",
    ".q-dialog input",
    "[role='dialog'] input[type='text']",
    "[role='dialog'] input",
]

_CHECKIN_CONFIRM_XPATHS = [
    "//button[.//span[contains(normalize-space(text()),'Confirmar')]]",
    "//button[.//span[contains(normalize-space(text()),'Fazer check-in')]]",
    "//button[.//span[contains(normalize-space(text()),'Fazer Check-in')]]",
    "//button[.//span[contains(normalize-space(text()),'Check-in')]]",
    "//button[.//span[contains(normalize-space(text()),'Checkin')]]",
    "//button[.//span[contains(normalize-space(text()),'Enviar')]]",
    "//button[.//span[contains(normalize-space(text()),'OK')]]",
    # Qualquer botão primário dentro do dialog que não seja Buscar nem Fechar
    ".//q-dialog //button[contains(@class,'bg-primary') and not(.//span[normalize-space(text())='Buscar'])]",
    "//button[@type='submit' and not(.//span[normalize-space(text())='Buscar'])]",
]


def _submit_checkin_modal(driver, checkin_code: str) -> bool:
    """
    Aguarda o modal de check-in abrir, insere o código e confirma.
    Retorna True se o check-in foi concluído, False em caso de falha não-crítica.
    """
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".q-dialog, [role='dialog']"))
    )
    print("  → Modal aberto. Inserindo código de check-in...")

    code_input = None
    for sel in _CHECKIN_INPUT_SELECTORS:
        try:
            code_input = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            break
        except Exception:
            continue

    if code_input is None:
        print("  ⚠  Input do código não encontrado no modal. Confirme manualmente.")
        return False

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", code_input)
    driver.execute_script("arguments[0].click();", code_input)
    driver.execute_script(
        "arguments[0].value = ''; arguments[0].dispatchEvent(new Event('input'));",
        code_input,
    )
    code_input.send_keys(checkin_code)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input'));"
        "arguments[0].dispatchEvent(new Event('change'));",
        code_input,
    )
    print(f"  → Código '{checkin_code}' inserido!")

    # Clica em "Buscar" para validar o código antes da confirmação final
    _BUSCAR_XPATH = (
        "//button[@type='submit' and .//span[normalize-space(text())='Buscar']]"
        " | //button[contains(@class,'bg-primary') and .//span[normalize-space(text())='Buscar']]"
        " | //button[.//span[normalize-space(text())='Buscar']]"
    )
    try:
        buscar_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, _BUSCAR_XPATH))
        )
        scroll_and_click(driver, buscar_btn)
        print("  → 'Buscar' clicado. Aguardando resultado...")
        # Aguarda o botão Buscar sumir ou o botão de confirmação aparecer
        WebDriverWait(driver, 10).until(
            lambda d: not d.find_elements(By.XPATH, _BUSCAR_XPATH)
                      or any(d.find_elements(By.XPATH, xp) for xp in _CHECKIN_CONFIRM_XPATHS)
        )
    except Exception:
        print("  ⚠  Botão 'Buscar' não encontrado — tentando confirmar diretamente.")

    for xpath in _CHECKIN_CONFIRM_XPATHS:
        try:
            confirm_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            scroll_and_click(driver, confirm_btn)
            print("✔  Check-in realizado com sucesso!")
            # Aguarda o modal fechar
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".q-dialog, [role='dialog']"))
            )
            return True
        except Exception:
            continue

    # Fallback: fecha o modal com Escape para não bloquear o fluxo principal
    print("⚠  Botão de confirmação não encontrado. Fechando modal e continuando...")
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        WebDriverWait(driver, 3).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".q-dialog, [role='dialog']"))
        )
    except Exception:
        pass
    return False


def try_checkin_from_home(driver, checkin_code: str) -> bool:
    """
    Verifica se há botão de check-in ativo na página atual (home) e o realiza.
    Aguarda até 5s para o Vue renderizar o botão após o carregamento.
    Retorna True se o check-in foi executado.
    """
    if not checkin_code:
        return False

    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, _XPATH_CHECKIN_ATIVO))
        )
    except Exception:
        return False  # sem botão ativo na home

    print("\n[→] Check-in disponível na página inicial. Realizando check-in...")
    scroll_and_click(driver, btn)
    return _submit_checkin_modal(driver, checkin_code)


def do_checkin(driver, checkin_code: str):
    """
    Realiza o check-in da primeira reserva disponível em 'Minhas Reservas'.

    Fluxo:
      1. Acessa /app/booking/my
      2. Clica no botão 'checkin' (quando habilitado)
      3. No modal que abre, insere o checkin_code
      4. Confirma
    """
    print("\n[→] Acessando 'Minhas Reservas' para check-in...")
    driver.get("https://totvs.deskbee.app/app/booking/my")
    handle_sso_login(driver, LOGIN, SENHA)

    # Aguarda ao menos um card de reserva carregar
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-bee='my-bookings.item.datetime']"))
    )

    # O botão ativo NÃO tem a classe 'booking-my-button-checkin-disable'
    # nem o atributo `disabled`. Procura a primeira ocorrência habilitada.
    print("  → Procurando botão de check-in habilitado...")
    try:
        btn_checkin = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, _XPATH_CHECKIN_ATIVO))
        )
    except Exception:
        todos = driver.find_elements(
            By.XPATH,
            "//button[contains(@class,'booking-my-button-checkin')"
            " and .//span[normalize-space(text())='checkin']]"
        )
        if todos:
            print("  ⚠  Botão de check-in ainda desabilitado — check-in não disponível agora. Pulando.")
        else:
            print("  ⚠  Botão de check-in não encontrado na página de reservas. Pulando.")
        return

    scroll_and_click(driver, btn_checkin)
    print("  → Botão de check-in clicado. Aguardando modal...")
    _submit_checkin_modal(driver, checkin_code)


# ── Data automática ──────────────────────────────────────────

def next_monday_after(date: datetime) -> datetime:
    """Retorna a próxima segunda-feira após a data informada."""
    days_ahead = 0 - date.weekday()  # 0 = segunda
    if days_ahead <= 0:
        days_ahead += 7
    return date + timedelta(days=days_ahead)


# handle_sso_login importado de sso_login.py


def get_last_reservation_date(driver) -> datetime:
    """
    Acessa 'Minhas reservas' e retorna a data da última reserva encontrada.
    Se não houver nenhuma reserva, retorna a data de hoje (a próxima segunda
    será calculada a partir daqui).
    """
    print("\n[→] Acessando 'Minhas reservas'...")
    driver.get("https://totvs.deskbee.app/app/booking/my")
    handle_sso_login(driver, LOGIN, SENHA)

    # Aguarda a página carregar (skeleton, lista vazia ou cards)
    try:
        WebDriverWait(driver, 15).until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "[data-bee='my-bookings.item.datetime']")
                or d.find_elements(By.CSS_SELECTOR, "[data-bee='my-bookings.empty']")
                or d.execute_script("return document.readyState") == "complete"
            )
        )
    except Exception:
        pass

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
        print("[→] Nenhuma reserva encontrada. Calculando a partir de hoje.")
        return datetime.today()

    last_date = max(dates)
    print(f"[→] Última reserva encontrada: {last_date.strftime('%d/%m/%Y')}")
    return last_date


# ── Fluxo principal ──────────────────────────────────────────
_RESERVA_ESTACAO_XPATHS = [
    # Seletor original
    "//span[contains(@class,'components__atom__button__label--space__icon')]"
    "//span[normalize-space(text())='Reserva Estação']",
    # Botão com texto direto
    "//button[.//*[normalize-space(text())='Reserva Estação']]",
    # Qualquer elemento clicável com esse texto
    "//*[normalize-space(text())='Reserva Estação']",
]


def _wait_home_ready(driver, timeout: int = 30):
    """Aguarda a home carregar verificando múltiplos seletores para 'Reserva Estação'."""
    def _home_pronta(d):
        for xpath in _RESERVA_ESTACAO_XPATHS:
            try:
                els = d.find_elements(By.XPATH, xpath)
                if els and els[0].is_displayed():
                    return True
            except Exception:
                pass
        return False

    try:
        WebDriverWait(driver, timeout).until(_home_pronta)
    except Exception:
        raise Exception(
            f"Página inicial não carregou o botão 'Reserva Estação' em {timeout}s.\n"
            f"URL atual: {driver.current_url}\n"
            "Verifique se o usuário tem permissão de reservar estação no DeskBee."
        )

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

        # 2. Acessa a página inicial
        print("\n[2/14] Acessando a página inicial...")
        driver.get("https://totvs.deskbee.app/app/home")
        handle_sso_login(driver, LOGIN, SENHA)

        # Check-in automático (se disponível e configurado)
        if CHECKIN_CODE:
            try_checkin_from_home(driver, CHECKIN_CODE)

        # Após o check-in, recarrega a home para garantir estado limpo
        print("  → Recarregando página inicial para continuar o fluxo de reserva...")
        driver.get("https://totvs.deskbee.app/app/home")
        handle_sso_login(driver, LOGIN, SENHA)
        _wait_home_ready(driver)

        # 3. Clicar em 'Reserva Estação'
        print("[3/14] Clicando em 'Reserva Estação'...")
        clicked = False
        for xpath in _RESERVA_ESTACAO_XPATHS:
            try:
                btn = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                scroll_and_click(driver, btn)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise Exception("Botão 'Reserva Estação' não encontrado na página inicial.")

        # Aguarda a página de reserva carregar
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[data-bee='booking.workspace.date']")
            )
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
        print(f"[14/14] Selecionando estação: {WORKSTATION}...")
        select_workstation(driver, WORKSTATION)
        time.sleep(1)

        print("\nProcesso concluído! (confirmação desabilitada para teste)")

    except Exception as e:
        msg = str(e)
        # Erros conhecidos da plataforma: exibe só a mensagem, sem traceback
        if msg.startswith("Reserva bloqueada pela plataforma:"):
            print(f"\n[AVISO] {msg}")
        else:
            print("\n[ERRO] Ocorreu um problema durante a automação:")
            traceback.print_exc()

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
