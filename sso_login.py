"""
sso_login.py
============
Autenticação SSO para o DeskBee / TOTVS.

Detecta a página de login, clica em 'Entrar com SSO', preenche
credenciais se necessário e aguarda o retorno ao app.
"""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def _is_in_app(driver) -> bool:
    """Retorna True se o driver já estiver dentro do app DeskBee."""
    return "deskbee.app/app/" in driver.current_url


def _sso_button_xpath() -> str:
    """Retorna um XPath union que cobre todas as variações do botão SSO."""
    return (
        "//button[@data-v-47011709 and .//*[normalize-space(text())='Entrar com SSO']]"
        " | //button[contains(@class,'components__button__primary')"
        "    and .//*[contains(normalize-space(text()),'Entrar com SSO')]]"
        " | //button[.//*[normalize-space(text())='Entrar com SSO']]"
        " | //button[contains(.,'Entrar com SSO')]"
    )


def _click_sso_button(driver, timeout: int = 10):
    """Clica em 'Entrar com SSO' — o botão já deve estar visível quando chamado."""
    xpath = _sso_button_xpath()
    btn = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    time.sleep(0.3)
    try:
        btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", btn)


def _fill_sso_credentials(driver, login: str, senha: str):
    """
    Se após clicar em 'Entrar com SSO' aparecer formulário com campos
    emailAddress / password, preenche-os e submete.
    Só age se login e senha estiverem preenchidos.
    """
    if not login or not senha:
        return

    try:
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "emailAddress"))
        )
    except Exception:
        return  # formulário não apareceu — SSO já autenticado

    print("  → Formulário SSO detectado. Preenchendo credenciais...")
    email_input.clear()
    email_input.send_keys(login)

    try:
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
    except Exception:
        raise Exception("Campo de senha não encontrado no formulário SSO.")

    password_input.clear()
    password_input.send_keys(senha)

    # Submete (botão de submit ou Enter como fallback)
    try:
        submit_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[@type='submit']"
                " | //button[contains(@class,'btn-primary')]"
                " | //input[@type='submit']",
            ))
        )
        submit_btn.click()
    except Exception:
        from selenium.webdriver.common.keys import Keys
        password_input.send_keys(Keys.RETURN)

    print("  → Credenciais enviadas. Aguardando redirecionamento...")


def _is_in_app(driver) -> bool:
    """Retorna True se o driver já estiver dentro do app DeskBee."""
    return "deskbee.app/app/" in driver.current_url


def _sso_button_xpath() -> str:
    """Retorna um XPath único que cobre todas as variações do botão SSO."""
    # OR de XPaths via union é mais eficiente que checar um a um
    return (
        "//button[@data-v-47011709 and .//*[normalize-space(text())='Entrar com SSO']]"
        " | //button[contains(@class,'components__button__primary')"
        "    and .//*[contains(normalize-space(text()),'Entrar com SSO')]]"
        " | //button[.//*[normalize-space(text())='Entrar com SSO']]"
        " | //button[contains(.,'Entrar com SSO')]"
    )


def handle_sso_login(driver, login: str = "", senha: str = "", timeout: int = 120):
    """
    Fallback de autenticação SSO.

    Como o script copia a sessão do Chrome instalado, o login normalmente já
    está ativo. Esta função apenas verifica se o Vue redirecionou para /login
    (sessão expirada) e, se sim, realiza o fluxo SSO.
    """
    # Aguarda a página carregar completamente
    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass

    # Dá até 4s para o Vue realizar o redirect para /login (se a sessão expirou).
    # Se após esse tempo a URL ainda não contiver /login → já está autenticado.
    xpath = _sso_button_xpath()
    try:
        WebDriverWait(driver, 4).until(
            lambda d: "/login" in d.current_url
                      or bool(d.find_elements(By.XPATH, xpath))
        )
    except Exception:
        return  # sem redirect e sem botão SSO → sessão ativa, nada a fazer

    # Sessão expirada: aguarda o botão ficar clicável e faz o login
    print("  → Sessão SSO expirada. Realizando login...")
    try:
        WebDriverWait(driver, 10).until(
            lambda d: bool(d.find_elements(By.XPATH, xpath))
        )
    except Exception:
        raise Exception("Redirecionado para /login mas o botão 'Entrar com SSO' não apareceu.")

    _click_sso_button(driver)
    _fill_sso_credentials(driver, login, senha)

    print(f"  → Aguardando conclusão do login SSO (até {timeout}s)...")
    WebDriverWait(driver, timeout).until(_is_in_app)
    print("  → Login SSO concluído!")
