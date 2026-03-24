"""
instalar.py
===========
Script de configuração inicial — execute UMA VEZ antes de usar o projeto.

  Linux / macOS:   python3 instalar.py
  Windows:         python instalar.py

O que ele faz:
  1. Verifica a versão do Python (mínimo 3.9)
  2. Cria um ambiente virtual (.venv) isolado no projeto
  3. Instala as dependências do requirements.txt dentro do .venv
  4. Verifica se o Google Chrome está instalado
  5. Verifica/copia o config.cfg a partir do exemplo
"""

import os
import platform
import shutil
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(HERE, ".venv")
SEP = "=" * 55

# Python do venv (criado abaixo)
_is_win = sys.platform == "win32"
VENV_PYTHON = os.path.join(VENV_DIR, "Scripts" if _is_win else "bin", "python.exe" if _is_win else "python")
VENV_PIP    = os.path.join(VENV_DIR, "Scripts" if _is_win else "bin", "pip.exe"    if _is_win else "pip")


def passo(n, total, msg):
    print(f"\n[{n}/{total}] {msg}...")


def ok(msg=""):
    print(f"  ✔  {msg}" if msg else "  ✔  OK")


def erro(msg):
    print(f"\n  ✘  ERRO: {msg}")
    sys.exit(1)


# ── 1. Versão do Python ─────────────────────────────────────

print(SEP)
print(" Configuração inicial — DeskBee / TOTVS")
print(SEP)

passo(1, 5, "Verificando versão do Python")
if sys.version_info < (3, 9):
    erro(
        f"Python 3.9+ é necessário. Versão detectada: {platform.python_version()}\n"
        "  Baixe em https://www.python.org/downloads/"
    )
ok(f"Python {platform.python_version()}")


# ── 2. Criar ambiente virtual ────────────────────────────────

passo(2, 5, "Criando ambiente virtual (.venv)")
if os.path.exists(VENV_PYTHON):
    ok(".venv já existe — reutilizando")
else:
    try:
        venv.create(VENV_DIR, with_pip=True, clear=False)
        ok(f".venv criado em {VENV_DIR}")
    except Exception as e:
        # Algumas distros Linux não têm o módulo venv embutido
        result = subprocess.run(
            [sys.executable, "-m", "virtualenv", VENV_DIR],
            capture_output=True,
        )
        if result.returncode != 0:
            erro(
                f"Não foi possível criar o .venv: {e}\n"
                "  No Ubuntu/Debian tente:  sudo apt install python3-venv\n"
                "  Depois execute este script novamente."
            )
        ok(f".venv criado em {VENV_DIR}")


# ── 3. Instalar dependências no venv ─────────────────────────

passo(3, 5, "Instalando dependências no .venv")
req_path = os.path.join(HERE, "requirements.txt")
if not os.path.exists(req_path):
    erro(f"requirements.txt não encontrado em {HERE}")

# Atualiza pip dentro do venv primeiro
subprocess.run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"],
               capture_output=True)

result = subprocess.run(
    [VENV_PYTHON, "-m", "pip", "install", "-r", req_path],
)
if result.returncode != 0:
    erro("Falha ao instalar dependências. Veja o erro acima.")
ok("Dependências instaladas no .venv")


# ── 4. Verificar Google Chrome ───────────────────────────────

passo(4, 5, "Verificando Google Chrome")
_sys = platform.system()

chrome_encontrado = False
if _sys == "Windows":
    candidatos = [
        os.path.join(os.environ.get("PROGRAMFILES", ""),      "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),      "Google", "Chrome", "Application", "chrome.exe"),
    ]
    chrome_encontrado = any(os.path.exists(c) for c in candidatos)
elif _sys == "Darwin":
    chrome_encontrado = os.path.exists("/Applications/Google Chrome.app")
else:
    chrome_encontrado = (
        shutil.which("google-chrome") is not None
        or shutil.which("google-chrome-stable") is not None
        or shutil.which("chromium-browser") is not None
    )

if chrome_encontrado:
    ok("Google Chrome encontrado")
else:
    print(
        "  ⚠  Google Chrome não detectado.\n"
        "     Baixe em https://www.google.com/chrome/ e instale antes de usar."
    )


# ── 5. Verificar config.cfg ──────────────────────────────────

passo(5, 5, "Verificando config.cfg")
cfg_path     = os.path.join(HERE, "config.cfg")
example_path = os.path.join(HERE, "config.cfg.example")

if os.path.exists(cfg_path):
    ok("config.cfg já existe")
elif os.path.exists(example_path):
    shutil.copy2(example_path, cfg_path)
    print(
        "  ✔  config.cfg criado a partir do exemplo.\n"
        "     ➜  Abra o arquivo e preencha suas informações antes de usar."
    )
else:
    print("  ⚠  config.cfg.example não encontrado. Crie o config.cfg manualmente.")


# ── Conclusão ────────────────────────────────────────────────

print(f"\n{SEP}")
print(" Tudo pronto! Os scripts usam o .venv automaticamente.")
print(" Para usar, basta executar normalmente:")
print("   python3 reservar_estacao.py   → faz a reserva")
print("   python3 fazer_checkin.py      → faz o check-in")
print(SEP)


