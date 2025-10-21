#!/bin/bash

# =================================================================================
# == AiKore - SCRIPT DE TEST V19 - SÉPARATION DES CHEMINS HTTP & WEBSOCKET ==
# =================================================================================

trap 'kill $(jobs -p) 2>/dev/null' EXIT

# -- Variables Instance 1 --
INSTANCE_NAME_1="test-vnc-1"
TEST_SERVER_PORT_1=31361
TMP_NGINX_CONF_FILE_1="/tmp/${INSTANCE_NAME_1}.conf"
NGINX_CONF_FILE_1="/etc/nginx/locations.d/${INSTANCE_NAME_1}.conf"
VNC_DISPLAY_NUM_1=11
VNC_DISPLAY_1=":${VNC_DISPLAY_NUM_1}"
VNC_RFB_PORT_1=$((5900 + VNC_DISPLAY_NUM_1))
WEBSOCKIFY_PORT_1=31363

# -- Variables Instance 2 --
INSTANCE_NAME_2="test-vnc-2"
TEST_SERVER_PORT_2=31362
TMP_NGINX_CONF_FILE_2="/tmp/${INSTANCE_NAME_2}.conf"
NGINX_CONF_FILE_2="/etc/nginx/locations.d/${INSTANCE_NAME_2}.conf"
VNC_DISPLAY_NUM_2=12
VNC_DISPLAY_2=":${VNC_DISPLAY_NUM_2}"
VNC_RFB_PORT_2=$((5900 + VNC_DISPLAY_NUM_2))
WEBSOCKIFY_PORT_2=31364

CONDA_PYTHON="/home/abc/miniconda3/bin/python"
NGINX_RELOAD_FLAG="/run/aikore/nginx_reload.flag"

echo "--- [TEST SCRIPT V19] Démarrage du test multi-instance ---"

# --- ÉTAPE 1: Démarrage des deux serveurs web ---
echo " "
echo "--- [1/4] Lancement des serveurs web ---"
mkdir -p /tmp/www1 /tmp/www2
echo "<h1>INSTANCE 1 - OK</h1>" > /tmp/www1/index.html
echo "<h1>INSTANCE 2 - OK</h1>" > /tmp/www2/index.html

cd /tmp/www1
${CONDA_PYTHON} -m http.server --bind 127.0.0.1 ${TEST_SERVER_PORT_1} &
SERVER_PID_1=$!

cd /tmp/www2
${CONDA_PYTHON} -m http.server --bind 127.0.0.1 ${TEST_SERVER_PORT_2} &
SERVER_PID_2=$!

sleep 1
if ! kill -0 ${SERVER_PID_1} 2>/dev/null || ! kill -0 ${SERVER_PID_2} 2>/dev/null; then
    echo "[ERREUR FATALE] Un des serveurs web n'a pas pu démarrer."
    exit 1
fi
echo "[SUCCÈS] Les deux serveurs web sont en cours d'exécution."

# --- ÉTAPE 2: Création des configurations NGINX ---
echo " "
echo "--- [2/4] Création et déplacement des configurations NGINX ---"
# Config Instance 1
cat > "${TMP_NGINX_CONF_FILE_1}" <<-EOF
# Chemin DÉDIÉ à la connexion WebSocket
location /ws/${INSTANCE_NAME_1}/ {
    proxy_pass http://127.0.0.1:${WEBSOCKIFY_PORT_1}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
}
# Chemin pour servir l'application (le client VNC)
location /app/${INSTANCE_NAME_1}/ {
    # Si la requête est pour la racine, on redirige vers le client
    # en lui passant le chemin du WebSocket à utiliser
    if (\$uri = /app/${INSTANCE_NAME_1}/) {
        return 302 /app/${INSTANCE_NAME_1}/vnc.html?autoconnect=true&path=ws/${INSTANCE_NAME_1}/;
    }
    # Pour les autres requêtes (vnc.html, css, js), on sert les fichiers
    proxy_pass http://127.0.0.1:${WEBSOCKIFY_PORT_1}/;
}
location /app/internal-test-1/ { proxy_pass http://127.0.0.1:${TEST_SERVER_PORT_1}/; }
EOF
mv "${TMP_NGINX_CONF_FILE_1}" "${NGINX_CONF_FILE_1}"

# Config Instance 2
cat > "${TMP_NGINX_CONF_FILE_2}" <<-EOF
location /ws/${INSTANCE_NAME_2}/ {
    proxy_pass http://127.0.0.1:${WEBSOCKIFY_PORT_2}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
}
location /app/${INSTANCE_NAME_2}/ {
    if (\$uri = /app/${INSTANCE_NAME_2}/) {
        return 302 /app/${INSTANCE_NAME_2}/vnc.html?autoconnect=true&path=ws/${INSTANCE_NAME_2}/;
    }
    proxy_pass http://127.0.0.1:${WEBSOCKIFY_PORT_2}/;
}
location /app/internal-test-2/ { proxy_pass http://127.0.0.1:${TEST_SERVER_PORT_2}/; }
EOF
mv "${TMP_NGINX_CONF_FILE_2}" "${NGINX_CONF_FILE_2}"

touch "${NGINX_RELOAD_FLAG}"
echo "Configurations NGINX en place et rechargement demandé."

# --- ÉTAPE 3: Démarrage des deux sessions VNC + Websockify ---
echo " "
echo "--- [3/4] Lancement des sessions VNC et des ponts websockify ---"
# Session 1
/usr/bin/Xvnc ${VNC_DISPLAY_1} -geometry 1280x800 -depth 24 -rfbport ${VNC_RFB_PORT_1} -SecurityTypes None &
/usr/bin/websockify -v --web /usr/share/novnc/ ${WEBSOCKIFY_PORT_1} 127.0.0.1:${VNC_RFB_PORT_1} &

# Session 2
/usr/bin/Xvnc ${VNC_DISPLAY_2} -geometry 1280x800 -depth 24 -rfbport ${VNC_RFB_PORT_2} -SecurityTypes None &
/usr/bin/websockify -v --web /usr/share/novnc/ ${WEBSOCKIFY_PORT_2} 127.0.0.1:${VNC_RFB_PORT_2} &

sleep 2
echo "[SUCCÈS] Sessions VNC démarrées."

# --- ÉTAPE 4: Démarrage des deux navigateurs Firefox ---
echo " "
echo "--- [4/4] Lancement des navigateurs Firefox dans leurs sessions respectives ---"
# Firefox 1 dans VNC 1
DISPLAY=${VNC_DISPLAY_1} firefox --no-sandbox "http://127.0.0.1:9000/app/internal-test-1/" &

# Firefox 2 dans VNC 2
DISPLAY=${VNC_DISPLAY_2} firefox --no-sandbox "http://127.0.0.1:9000/app/internal-test-2/" &

echo " "
echo "--- [TEST MULTI-INSTANCE PRÊT] ---"
echo "Instructions de validation :"
echo "  1. Ouvrez un onglet sur http://<votre-ip>:19000/app/test-vnc-1/"
echo "     -> Vous devriez voir directement le Firefox affichant 'INSTANCE 1 - OK'."
echo "  2. Ouvrez un autre onglet sur http://<votre-ip>:19000/app/test-vnc-2/"
echo "     -> Vous devriez voir directement le Firefox affichant 'INSTANCE 2 - OK'."

wait