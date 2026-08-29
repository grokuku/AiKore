# Authentification applicative (AIKORE_API_KEY)

Authentification par **token statique** définie via la variable d'environnement `AIKORE_API_KEY`.

- **Clé présente** → auth **activée**, mode *fail-closed* : toute requête HTTP ou WebSocket non publique doit présenter la clé.
- **Clé absente/vide** → auth **désactivée** (comportement historique), avec un `[WARNING]` affiché au démarrage.

## Activation

```bash
# Générer une clé forte
openssl rand -hex 32
```

```yaml
# docker-compose.yml
services:
  aikore:
    environment:
      - AIKORE_API_KEY=collez_ici_la_cle_generee   # >= 24 caractères recommandés
```

Puis redémarrer le conteneur. Un avertissement est émis au démarrage si la clé fait moins de 24 caractères.

## Comment ça marche

| Transport | Mécanisme |
|---|---|
| HTTP | Header `Authorization: Bearer <clé>` **ou** `X-API-Key: <clé>` |
| WebSocket | Mêmes headers, ou subprotocols offerts `['aikore-auth', '<clé>']` — le serveur répond `'aikore-auth'` et ne renvoie **jamais** la clé |

- Comparaison en temps constant (`secrets.compare_digest`).
- Réponse HTTP en cas d'échec : `401` + `{"detail":"Invalid or missing API key"}` + `WWW-Authenticate: Bearer`.
- WebSocket : handshake refusé **avant** `accept()` (le navigateur voit un échec de connexion).
- **Origine WS** : si l'en-tête `Origin` est présent et que son host ≠ `Host` de la requête, ≠ `X-Forwarded-Host` (fallback proxy) et ≠ origines autorisées (`AIKORE_WS_ALLOWED_ORIGINS`), le handshake est refusé avec le log `[AUTH] Blocked cross-origin WS`. Voir [Compatibilité proxy](#compatibilité-proxy-check-origine-websocket).
- Chemins publics (sans auth) : `/`, `/favicon.ico`, `/static/*` — complétés par `AIKORE_AUTH_PUBLIC_PATHS`.
- Le frontend lit `window.AIKORE_API_KEY` (stub inline dans `index.html`) et attache automatiquement les headers / subprotocols. En production derrière un proxy, il suffit que le proxy injecte la clé côté backend ; le navigateur n'a pas besoin de la connaître pour les appels fetch (seuls les WebSockets du navigateur la transportent en subprotocol).

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `AIKORE_API_KEY` | *(vide = auth désactivée)* | Clé API statique ; active l'authentification si non vide |
| `AIKORE_WS_ALLOWED_ORIGINS` | *(vide)* | Origines supplémentaires autorisées pour les WebSockets, séparées par virgules (ex. `https://aikore.example.com,https://alt.example.net`) |
| `AIKORE_AUTH_PUBLIC_PATHS` | *(vide)* | Chemins publics additionnels, séparés par virgules (`/path` = exact, `/prefix*` = préfixe) |
| `AIKORE_ENABLE_DEBUG_NGINX` | `true` | Mettre à `false` pour désactiver `/api/system/debug-nginx` (répond 404, même authentifié) |

## Exemple Caddy 2 (+ Authentik)

Le proxy fait l'authentification SSO (Authentik), puis remplace l'en-tête `Authorization` par la clé statique attendue par AiKore :

```caddyfile
aikore.example.com {
    # SSO Authentik (forward_auth)
    forward_auth authentik:9000 {
        uri /outpost.goauthentik.io/auth/nginx
    }

    reverse_proxy aikore:9000 {
        # AiKore ne voit que la clé statique, jamais le token utilisateur
        header_up Authorization "Bearer {env.AIKORE_API_KEY}"
    }
}
```

> `{env.AIKORE_API_KEY}` est résolu depuis l'environnement du process Caddy — pensez à y définir la même clé que celle du conteneur AiKore.

## Compatibilité proxy (check Origine WebSocket)

La validation d'origine des WebSockets compare l'en-tête `Origin` à l'hôte de la requête. Derrière un reverse proxy, celui-ci doit donc transmettre l'hôte public d'origine :

- **Caddy 2** : préserve le `Host` d'origine par défaut (`reverse_proxy`) — rien à faire.
- **nginx** : ajouter `proxy_set_header Host $host;` dans le bloc `location`, sinon nginx transmet le nom upstream et tous les handshakes WS seront bloqués en cross-origin.
- **Fallback** : si un proxy ne peut pas préserver `Host`, AiKore accepte aussi une correspondance entre `Origin` et l'en-tête `X-Forwarded-Host` (chaîne multi-proxy gérée).
- **Dernier recours** : lister explicitement l'origine publique dans `AIKORE_WS_ALLOWED_ORIGINS` (ex. `https://aikore.example.com`).

> Note : les navigateurs ne peuvent pas forger `Origin` ni `X-Forwarded-Host` sur un handshake WebSocket ; ce fallback n'affaiblit donc pas la protection anti drive-by.

## Healthcheck Docker avec header

Quand l'auth est activée, `/api/status` exige la clé :

```yaml
services:
  aikore:
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS -H \"X-API-Key: $$AIKORE_API_KEY\" http://localhost:9000/api/status || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
```

(`$$` = échappement Compose ; la variable est développée dans le conteneur.)

## Limites connues

- **KasmVNC hors périmètre** : les ports des instances (9001–9020) servent les UI des instances sans authentification applicative AiKore. Ils doivent être protégés au niveau du proxy/pare-feu (non exposés publiquement).
- **Rotation de clé = redémarrage** : la clé est lue une seule fois au démarrage ; changer `AIKORE_API_KEY` impose de recréer le conteneur.
- **Secret visible côté navigateur** : la clé configurée dans le frontend transite dans les subprotocols WebSocket (visible dans les devtools). C'est un secret de périmètre applicatif — l'authentification utilisateur reste déléguée au proxy (Authentik).
- **Téléchargement des wheels** : passe par `fetch` + blob (pour porter le header d'auth), donc chargé en mémoire avant enregistrement — les très gros fichiers consomment temporairement de la RAM côté navigateur.
