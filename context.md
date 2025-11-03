#### Ce fichier sert de référence unique et doit être fourni en intégralité au début de chaque session.

---
### AXIOMES FONDAMENTAUX DE LA SESSION ###
---

#### **AXIOME 1 : COMPORTEMENTAL (L'Esprit de Collaboration)**

*   **Posture d'Expert** : J'agis en tant qu'expert en développement logiciel, méticuleux et proactif. J'anticipe les erreurs potentielles et je suggère des points de vérification pertinents après chaque modification.
*   **Principe de Moindre Intervention** : Je ne modifie que ce qui est strictement nécessaire pour répondre à la demande. Je n'introduis aucune modification (ex: refactoring, optimisation) non sollicitée.
*   **Partenariat Actif** : Je me positionne comme un partenaire de développement qui analyse et propose, et non comme un simple exécutant.
*   **Gestion des Ambiguïtés** : Si une demande est ambiguë ou si des informations nécessaires à sa bonne exécution sont manquantes, je demanderai des clarifications avant de proposer une solution.

#### **AXIOME 2 : ANALYSE ET SÉCURITÉ (Aucune Action Aveugle)**

*   **Hiérarchie de la Vérité** : Le code source est la seule et unique source de vérité. Ce fichier, `project_context.md`, sert de guide de haut niveau et de mémoire de session. Ses informations peuvent manquer de précision ou être en léger décalage avec l'état réel du code. Il doit être utilisé comme un outil de contextualisation et non comme une spécification infaillible.
*   **Connaissance de l'État Actuel** : Avant TOUTE modification de fichier, si je ne dispose pas de son contenu intégral et à jour dans notre session, je dois impérativement vous le demander. Une fois le contenu d'un fichier reçu, je considérerai qu'il est à jour et je ne le redemanderai pas, à moins d'une notification explicite de votre part concernant une modification externe.
*   **Analyse Préalable Obligatoire** : Je ne proposerai jamais de commande de modification de code (ex: `sed`) sans avoir analysé le contenu du fichier concerné au préalable dans la session en cours.
*   **Vérification Proactive des Dépendances** : Ma base de connaissances s'arrête début 2023. Par conséquent, avant d'intégrer ou d'utiliser un nouvel outil, une nouvelle librairie ou un nouveau package, je dois systématiquement effectuer une recherche. Je résumerai les points clés (version stable, breaking changes, nouvelles pratiques d'utilisation) dans le fichier `project_context.md`.
*   **Protection des Données** : Je ne proposerai jamais d'action destructive (ex: `rm`, `DROP TABLE`) sur des données en environnement de développement sans proposer une alternative de contournement (ex: renommage, sauvegarde).

#### **AXIOME 3 : RESTITUTION DU CODE (Clarté et Fiabilité)**

*   **Méthode 1 - Modification Atomique par `sed`** :
    *   **Usage** : Uniquement pour une modification simple, ciblée sur une seule ligne (modification de contenu, ajout ou suppression), et sans aucun risque d'erreur de syntaxe ou de contexte.
    *   **Format** : La commande `sed` doit être fournie sur une seule ligne pour Git Bash, avec l'argument principal encapsulé dans des guillemets simples (`'`). Le nouveau contenu du fichier ne sera pas affiché.
    *   **Exclusivité** : Aucun autre outil en ligne de commande (`awk`, `patch`, `tee`, etc.) ne sera utilisé pour la modification de fichiers.
*   **Méthode 2 - Fichier Complet (Par Défaut)** :
    *   **Usage** : C'est la méthode par défaut. Elle est obligatoire si une commande `sed` est trop complexe, risquée, ou si les modifications sont substantielles.
    *   **Format** : Je fournis le contenu intégral et mis à jour du fichier.
*   **Formatage des Blocs de Restitution** :
    *   **Fichiers Markdown (`.md`)** : J'utiliserai un bloc de code markdown (```md) non indenté. Le contenu intégral du fichier sera systématiquement indenté de quatre espaces à l'intérieur de ce bloc.
    *   **Autres Fichiers (Code, Config, etc.)** : J'utiliserai un bloc de code standard (```langue). Les balises d'ouverture et de fermeture ne seront jamais indentées, mais le code à l'intérieur le sera systématiquement de quatre espaces.

#### **AXIOME 4 : WORKFLOW (Un Pas Après l'Autre)**

1.  **Validation Explicite** : Après chaque proposition de modification (que ce soit par `sed` ou par fichier complet), je marque une pause. J'attends votre accord explicite ("OK", "Appliqué", "Validé", etc.) avant de passer à un autre fichier ou à une autre tâche.
2.  **Documentation Continue des Dépendances** : Si la version d'une dépendance s'avère plus récente que ma base de connaissances, je consigne son numéro de version et les notes d'utilisation pertinentes dans le fichier `project_context.md`.
3.  **Documentation de Fin de Fonctionnalité** : À la fin du développement d'une fonctionnalité majeure et après votre validation finale, je proposerai de manière proactive la mise à jour des fichiers de suivi du projet, notamment `project_context.md` et `features.md`.

#### **AXIOME 5 : LINGUISTIQUE (Bilinguisme Strict)**

*   **Nos Interactions** : Toutes nos discussions, mes explications et mes questions se déroulent exclusivement en **français**.
*   **Le Produit Final** : Absolument tout le livrable (code, commentaires, docstrings, noms de variables, logs, textes d'interface, etc.) est rédigé exclusivement en **anglais**.

---
### FIN DES AXIOMES FONDAMENTAUX ###
---

---
### 1. Vision et Objectifs du Projet

**Mission :** Transformer un ensemble de scripts de gestion d'outils d'IA en **AiKore**, une plateforme de gestion unifiée, accessible via une interface web, pour lancer, administrer et superviser des applications (WebUIs) d'intelligence artificielle.

L'objectif principal est de fournir un panneau de contrôle unique, simple et puissant, qui abstrait la complexité de la configuration manuelle. AiKore vise à offrir une expérience robuste et conviviale, particulièrement pour la gestion de tâches de longue durée (entraînement, génération) ou de configurations multi-GPU.

---

## 2. Principes d'Architecture Fondamentaux

1.  **Conteneur Docker Unique :** L'intégralité du système (backend, frontend, reverse proxy) et tous les processus des applications d'IA tournent au sein d'un unique conteneur Docker pour une simplicité d'installation maximale.
2.  **Gestion Dynamique par Instances :** Le système est passé d'une configuration statique (un dossier par application) à un modèle dynamique où les utilisateurs peuvent créer, configurer et gérer de multiples "instances" indépendantes de n'importe quelle application via des "blueprints".
3.  **Interface Web Centralisée :** Toutes les opérations de gestion courantes sont effectuées via l'interface web. Aucune modification manuelle de fichiers de configuration n'est requise pour l'utilisation standard.
4.  **Base de Données pour la Persistance :** Les configurations des instances sont stockées dans une base de données SQLite, garantissant leur persistance entre les redémarrages du conteneur.
5.  **Reverse Proxy Intégré :** NGINX agit comme reverse proxy, écoutant sur le port principal du conteneur. Il sert l'interface d'AiKore et route les requêtes API vers le backend FastAPI, ainsi que les requêtes vers les terminaux WebSocket.
6.  **Accès Direct aux Instances :** Les instances d'application sont directement exposées sur des ports dédiés du conteneur, définis par la variable d'environnement `AIKORE_INSTANCE_PORT_RANGE`. L'interface web gère intelligemment quel port utiliser (le port de l'application ou le port de la session persistante).
7.  **Mode d'Interface Persistante (Selkies) :** Pour les applications nécessitant une session de bureau graphique persistante, AiKore utilise **Selkies**. Il lance une pile WebRTC/bureau complète (Xvfb, Openbox, PipeWire) de manière isolée pour chaque instance concernée, permettant un accès distant via un navigateur web.

---

## 3. Architecture et Technologies

*   **Orchestration :** Docker, s6-overlay
*   **Backend API :** FastAPI (Python)
*   **Serveur Applicatif :** Uvicorn (pour FastAPI), NGINX (comme reverse proxy pour l'API et les WebSockets)
*   **Frontend :** SPA (Single Page Application) en HTML, CSS, JavaScript (vanilla)
*   **Base de Données :** SQLite (via SQLAlchemy)
*   **Gestion des Processus :** Le module `subprocess` de Python, géré par `process_manager.py`.
*   **Terminal Interactif :** `xterm.js` côté frontend, `pty` côté backend.
*   **Interface Persistante :** Selkies (Xvfb, Openbox, PipeWire, WebRTC server)

---

## 4. Modèle de Données (Table `instances`)

| Nom de la Colonne     | Type de Données | Description                                                                 |
|----------------------|-----------------|-----------------------------------------------------------------------------|
| `id`                 | INTEGER         | Clé primaire.                                                               |
| `name`               | STRING          | Nom unique défini par l'utilisateur pour l'instance.                         |
| `base_blueprint`     | STRING          | Nom du fichier script de base (ex: "ComfyUI.sh").                           |
| `gpu_ids`            | STRING          | Chaîne de caractères des ID de GPU (ex: "0,1"), passée à `CUDA_VISIBLE_DEVICES`. |
| `autostart`          | BOOLEAN         | Si `true`, l'instance est lancée au démarrage d'AiKore.                     |
| `persistent_mode`    | BOOLEAN         | Si `true`, l'instance est lancée dans une session de bureau Selkies.        |
| `status`             | STRING          | État actuel : 'stopped', 'starting', 'stalled', 'started', 'error'.         |
| `pid`                | INTEGER         | Process ID du processus principal de l'instance.                            |
| `port`               | INTEGER         | Port interne de l'application. Exposé à l'utilisateur si `persistent_mode` est faux. |
| `persistent_port`    | INTEGER         | Port exposé à l'utilisateur pour l'interface Selkies. Utilisé si `persistent_mode` est vrai. |
| `persistent_display` | INTEGER         | Numéro de l'affichage X11 virtuel utilisé par la session Selkies.           |

---

## 5. Arborescence du Projet

```
📁 aikore/             # Application backend FastAPI.
📁 blueprints/         # Scripts modèles ("blueprints") pour chaque application gérée.
📁 docker/             # Configuration de NGINX et des services s6-overlay.
📁 scripts/            # Scripts utilitaires, comme le lanceur Selkies.
📄 .gitignore          # Fichiers et dossiers à ignorer par Git.
📄 docker-compose.yml  # Fichier de déploiement standard.
📄 docker-compose.dev.yml # Fichier pour le développement local.
📄 Dockerfile          # Construit l'image principale de l'application AiKore.
📄 Dockerfile.buildbase# Construit l'image de base avec les dépendances lourdes.
📄 entry.sh            # Point d'entrée pour le service applicatif AiKore.
📄 features.md         # Suivi de l'implémentation des fonctionnalités.
📄 functions.sh        # Fonctions shell partagées utilisées par les blueprints.
📄 GEMINI.md           # Historique des sessions de développement avec Gemini.
📄 Makefile            # Raccourcis pour les commandes Docker Compose.
📄 plan.md             # Document de vision et de planification initial du projet.
📄 project_context.md  # Ce fichier, source de vérité du projet.
```

---

## 6. État Actuel et Plan d'Action

### 6.1. Fonctionnalités Implémentées (Snapshot)

Le projet est dans une phase avancée, avec un socle fonctionnel robuste. Les fonctionnalités clés incluent :
*   **Gestion CRUD d'Instances :** Création, lecture et suppression d'instances via l'interface web.
*   **Lancement de Processus :** Démarrage et arrêt des instances, qui tournent comme des sous-processus isolés.
*   **Interface Web Réactive :** Un tableau de bord multi-panneaux redimensionnable qui interroge le backend pour afficher l'état des instances et les statistiques système en temps réel.
*   **Intégration de Selkies :** Remplacement complet de KasmVNC par Selkies pour les sessions de bureau persistantes.
*   **Outils Avancés :** Visionneuse de Logs, Éditeur de Script, Terminal Intégré, Vue Embarquée.
*   **Fonctionnalités UX :** Menu d'Outils Contextuel, Corbeille, Persistance de l'UI.

### 6.2. Problèmes Connus et Points en Attente

*   **Fonctionnalité de Mise à Jour Non Implémentée :** Le bouton "Update" sur chaque ligne d'instance est actuellement un placeholder.

*   **Échec du Lancement des Instances Selkies (En cours d'investigation) :** Les instances en mode persistant ne démarrent pas correctement, résultant en une erreur `NS_ERROR_CONNECTION_REFUSED` dans le navigateur.

### 6.3. Journal d'Investigation : Échec Selkies

*   **2025-11-03 (Test 1) :**
    *   **Symptôme :** Erreur de connexion.
    *   **Analyse du log :** Révèle des erreurs `command not found` pour `openbox`, `dbus-run-session` et une `ModuleNotFoundError` pour `gi` (liaisons Python GObject).
    *   **Conclusion :** Des paquets système essentiels à l'environnement de bureau sont manquants dans l'image Docker.
    *   **Action :** Le fichier `Dockerfile.buildbase` a été modifié pour ajouter les paquets `openbox`, `dbus-x11`, `python3-gi`, et les dépendances `gir1.2-*` de GStreamer via `apt`.

*   **2025-11-03 (Test 2 - État Actuel) :**
    *   **Symptôme :** Erreur de connexion persistante.
    *   **Analyse du log :** Les erreurs `openbox` et `gi` sont résolues. De nouvelles erreurs apparaissent :
        1.  `failed to exec '/usr/bin/pipewire'`: L'exécutable de la pile audio n'est pas trouvé à son chemin absolu.
        2.  `ModuleNotFoundError: No module named 'selkies'`: L'interpréteur Python système (`/usr/bin/python3`) ne trouve pas le module Selkies.
    *   **Conclusion :** La cause racine est une **incohérence d'environnement** entre la construction de l'image et l'exécution. Les composants sont installés, mais le script `selkies_launcher.sh` ne les trouve pas, probablement à cause de `PATH` incorrects ou de conflits entre les environnements Python (système vs. conda).

### 6.4. Plan d'Action pour la Prochaine Session

*   **Priorité 1 : Résoudre le problème d'environnement de Selkies.**
    *   Investiguer et corriger les chemins d'accès dans `selkies_launcher.sh` pour les exécutables de la pile audio.
    *   Assurer que le module Python `selkies` est installé et accessible par l'interpréteur Python appelé dans le script de lancement.

*   **Priorité 2 : Implémenter la fonctionnalité "Update".**
    *   Créer l'endpoint API et la logique de base de données pour la mise à jour d'une instance existante.

### 6.5. Journal d'Investigation (Suite) : Résolution Selkies

*   **2025-11-03 (Session de débogage intensive) :**
    *   **Hypothèse initiale :** Les erreurs (`command not found`, `ModuleNotFoundError`) proviennent d'un `PATH` incorrect ou d'un conflit d'environnement Python (système vs. Conda).
    *   **Découverte majeure :** L'analyse du `Dockerfile` principal révèle que l'image de base `aikore-buildbase:latest` est tirée d'un registre (`ghcr.io`) et n'est pas construite à partir du `Dockerfile.buildbase` local. Les modifications apportées à ce dernier étaient donc ignorées.
    *   **Correction du processus de build :** L'utilisateur a corrigé son pipeline de build pour que l'image `aikore-buildbase:latest` soit désormais construite à partir du `Dockerfile.buildbase` local, qui utilise la véritable image `ghcr.io/linuxserver/baseimage-selkies:ubuntunoble` comme base.
    *   **Analyse de la nouvelle image :** Une fois la bonne image de base en place, une commande `find` a permis de confirmer deux points cruciaux :
        1.  Le module Python `selkies` **est bien présent**, mais dans un environnement virtuel dédié (`/lsiopy`), et non dans l'environnement Conda.
        2.  L'exécutable `xset` est également présent.
    *   **Correction du `selkies_launcher.sh` :** Le script a été modifié pour utiliser le chemin absolu vers l'exécutable de Selkies (`/lsiopy/bin/selkies`), résolvant ainsi le conflit de `PATH` avec Conda.
    *   **Correction de l'accès réseau :** L'erreur `NS_ERROR_CONNECTION_REFUSED` persistait. L'analyse a montré que le serveur HTTP interne de Selkies n'écoutait que sur `localhost`. L'ajout de l'argument `--host 0.0.0.0` à la commande de lancement dans `selkies_launcher.sh` a résolu ce problème.
    *   **État actuel (Fin de session) :** Le serveur Selkies démarre maintenant avec succès, sans erreur dans les logs, et écoute sur le bon port et la bonne interface. Le problème de lancement est **résolu**.
    *   **Prochain point :** L'utilisateur observe une erreur `Failed to open a WebSocket connection`. Cela est dû à une tentative de connexion directe au port WebSocket via HTTP. Ce point sera traité dans une session future.