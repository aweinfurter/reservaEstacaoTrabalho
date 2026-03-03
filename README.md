# Reserva de Estação de Trabalho — DeskBee/TOTVS

Script Python com Selenium para automatizar a reserva de estação no portal
`https://totvs.deskbee.app`.

---

## Pré-requisitos

| Item | Detalhe |
|------|---------|
| Python 3.10+ | `python3 --version` |
| Google Chrome | já instalado |
| ChromeDriver | instalado automaticamente pelo Selenium Manager (Selenium ≥ 4.6) |

---

## Instalação

```bash
cd ~/Documentos/estacaoTrabalho
pip3 install -r requirements.txt
```

---

## Configuração

Edite as constantes no topo de `reservar_estacao.py`:

```python
TARGET_DAY   = 1       # Dia da reserva
TARGET_MONTH = 3       # Mês (1-12)
TARGET_YEAR  = 2026    # Ano

START_TIME = "0800"    # Horário de início (hhmm)
END_TIME   = "1800"    # Horário de fim    (hhmm)

BUILDING    = "Joinville › Santa Catarina - Bloco B"
FLOOR       = "3º Andar"
WORKSTATION = "B063"

CHROME_PROFILE_DIR = os.path.expanduser("~/.config/google-chrome")
CHROME_PROFILE     = "Default"   # Perfil já autenticado via SSO
```

> **Atenção:** O Google Chrome precisa estar **completamente fechado** antes de
> executar o script, pois o Selenium reabre o mesmo perfil.

---

## Uso

```bash
python3 reservar_estacao.py
```

O script irá:

1. Abrir o Chrome com seu perfil (já logado via SSO)
2. Acessar `https://totvs.deskbee.app/app/home`
3. Clicar em **Reserva Estação**
4. Selecionar a data no calendário
5. Preencher horários de início e fim
6. Selecionar o prédio e o andar via dropdown
7. Escolher a estação `B063`
8. Confirmar a reserva automaticamente

Ao final, aguarda um `ENTER` para fechar o browser.

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
|---------|---------------|---------|
| `DevToolsActivePort` / Chrome não abre | Chrome já estava aberto | Feche todas as janelas do Chrome antes |
| Elemento não encontrado | Página ainda carregando | Aumente o `timeout` nas chamadas `WebDriverWait` |
| Estação não encontrada | Nome diferente no mapa | Ajuste `WORKSTATION` para o texto exato exibido na tela |
| Botão de confirmação não encontrado | Texto do botão diferente | Adicione o texto correto em `confirm_reservation()` |
# reservaEstacaoTrabalho
