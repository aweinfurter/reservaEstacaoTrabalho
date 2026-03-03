#!/usr/bin/env bash
# Fecha o Chrome atual e reabre com a porta de debug remoto habilitada.
# Isso permite que o script Selenium se conecte sem precisar fechar o Chrome.

PROFILE_DIR="$HOME/.config/google-chrome"
PROFILE="Default"
DEBUG_PORT=9222

echo "Fechando Chrome existente..."
pkill -f "/opt/google/chrome/chrome" 2>/dev/null || true
pkill -f "google-chrome"             2>/dev/null || true
sleep 3

# Remove lock files que impedem nova instância com o mesmo perfil
rm -f "$PROFILE_DIR/$PROFILE/SingletonLock" 2>/dev/null || true
rm -f "$PROFILE_DIR/$PROFILE/SingletonSocket" 2>/dev/null || true
rm -f "$PROFILE_DIR/SingletonLock" 2>/dev/null || true

echo "Abrindo Chrome com debug remoto na porta $DEBUG_PORT..."
nohup google-chrome \
  --remote-debugging-port=$DEBUG_PORT \
  --profile-directory="$PROFILE" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  > /tmp/chrome_debug.log 2>&1 &

echo "Aguardando Chrome iniciar..."
for i in $(seq 1 15); do
  sleep 1
  if curl -s "http://localhost:$DEBUG_PORT/json/version" > /dev/null 2>&1; then
    echo "✔  Chrome pronto na porta $DEBUG_PORT!"
    echo "Agora execute: python3 reservar_estacao.py"
    exit 0
  fi
  echo "  ... aguardando ($i/15)"
done

echo "✘  Chrome não respondeu na porta $DEBUG_PORT. Verifique /tmp/chrome_debug.log"
exit 1
