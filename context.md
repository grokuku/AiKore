#### Ce fichier sert de référence unique et doit être fourni en intégralité au début de chaque session.

---
### AXIOMES FONDAMENTAUX DE LA SESSION ###
---

#### **AXIOME 1 : COMPORTEMENTAL (L'Esprit de Collaboration)**

*   **Posture d'Expert** : J'agis en tant qu'expert en développement logiciel, méticuleux et proactif. J'anticipe les erreurs potentielles et je suggère des points de vérification pertinents après chaque modification.
*   **Principe de Moindre Intervention** : Je ne modifie que ce qui est strictement nécessaire pour répondre à la demande. Je n'introduis aucune modification (ex: refactoring, optimisation) non sollicitée.
*   **Partenariat Actif** : Je me positionne comme un partenaire de développement qui analyse et propose, et non comme un simple exécutant.
*   **Gestion des Ambiguïtés** : Si une demande est ambiguë ou si des informations nécessaires à sa bonne exécution sont manquantes, je demanderai des clarifications avant de proposer une solution.

#### **AXIOME 2 : ANALYSE ET SÉCURITÉ (Aucune Action Avele)**

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
5.  **Accès aux Instances :**
    *   **Mode Normal :** NGINX agit comme reverse proxy, routant les requêtes ` /instance/<nom_instance>/` vers le port interne de l'application correspondante.
    *   **Mode Persistant (Selkies) :** L'instance est directement exposée sur un port dédié du conteneur (ex: 19001), défini par `AIKORE_INSTANCE_PORT_RANGE`. NGINX n'est pas utilisé pour ces instances.
6.  **Mode d'Interface Persistante (Selkies) :** Pour les applications nécessitant une session de bureau graphique persistante, AiKore utilise **Selkies**. Il lance une pile WebRTC/bureau complète de manière isolée pour chaque instance concernée, permettant un accès distant via un navigateur web.

---

## 3. Architecture et Technologies

*   **Orchestration :** Docker, s6-overlay
*   **Backend API :** FastAPI (Python)
*   **Serveur Applicatif :** Uvicorn (pour FastAPI), NGINX (comme reverse proxy)
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
| `port`               | INTEGER         | Port interne de l'application (toujours utilisé, souvent éphémère).         |
| `persistent_port`    | INTEGER         | Port exposé à l'utilisateur pour l'interface Selkies. Utilisé si `persistent_mode` est vrai. |
| `persistent_display` | INTEGER         | Numéro de l'affichage X11 virtuel utilisé par la session Selkies.           |

---

## 5. Arborescence du Projet

```
📁 aikore/
    📁 api/
    📄 __init__.py
    📄 instances.py
    📄 system.py
    📁 core/
    📄 __init__.py
    📄 process_manager.py
    📁 database/
    📄 __init__.py
    📄 crud.py
    📄 models.py
    📄 session.py
    📁 schemas/
    📄 __init__.py
    📄 instance.py
    📁 static/
    📁 welcome/
        📁 js/
        📄 effects.js
        📄 main.js
        📄 renderer.js
        📁 logos/
        📄 ... (fichiers logo)
        📄 index.html
        📄 style.css
    📄 app.js
    📄 index.html
    📄 style.css
    📄 main.py
    📄 requirements.txt
📁 blueprints/
    📁 legacy/
    📄 ... (anciens blueprints)
    📄 ComfyUI.sh
    📄 FluxGym.sh
📁 docker/
    📁 root/
    📁 etc/
        📁 nginx/
        📁 conf.d/
            📄 aikore.conf
        📁 s6-overlay/
        📁 s6-rc.d/
            📄 ... (services s6)
        📁 sudoers.d/
        📄 aikore-sudo
📁 scripts/
    📄 selkies_launcher.sh
📄 .gitignore
📄 docker-compose.dev.yml
📄 docker-compose.yml
📄 Dockerfile
📄 Dockerfile.buildbase
📄 entry.sh
📄 features.md
📄 functions.sh
📄 GEMINI.md
📄 Makefile
📄 plan.md
📄 project_context.md
```

---

## 6. État Actuel et Plan d'Action

### 6.1. Fonctionnalités Implémentées (Snapshot)

Le projet est dans une phase avancée, avec un socle fonctionnel robuste. Les fonctionnalités clés incluent :
*   **Gestion CRUD d'Instances :** Création, lecture et suppression d'instances via l'interface web.
*   **Lancement de Processus :** Démarrage et arrêt des instances.
*   **Interface Web Réactive :** Tableau de bord multi-panneaux avec état et statistiques en temps réel.
*   **Intégration de Selkies :** Les instances persistantes lancent un serveur Selkies autonome.
*   **Accès Direct aux Instances Persistantes :** L'architecture est en place pour que les instances Selkies soient accessibles directement sur leur `persistent_port`, en contournant NGINX.
*   **Outils Avancés :** Visionneuse de Logs, Éditeur de Script, Terminal Intégré, Vue Embarquée.
*   **Fonctionnalités UX :** Menu d'Outils Contextuel, Corbeille, Persistance de l'UI.

### 6.2. Problèmes Connus et Points en Attente

*   **Fonctionnalité de Mise à Jour Non Implémentée :** Le bouton "Update" sur chaque ligne d'instance est actuellement un placeholder.
*   **Erreur de Connexion aux Instances Persistantes :** La fonctionnalité est presque complète, mais un bug dans le code frontend empêche l'accès correct.

### 6.3. Journal d'Investigation

*   **2025-11-03 :** Résolution des problèmes de dépendances et de `PATH` pour le lanceur Selkies. Le serveur Selkies démarre maintenant correctement, sans erreur dans les logs, et écoute sur le bon port.

*   **2025-11-04 (État Actuel) :**
    *   **Symptôme 1 :** Cliquer sur "Open" pour une instance persistante redirige vers une URL incorrecte (ex: `http://<host>:19000/instance/test8/`), provoquant une erreur `404 Not Found`. L'URL devrait être `http://<host>:19001/`.
    *   **Symptôme 2 :** En accédant manuellement à l'URL correcte, une erreur de connexion WebSocket se produit, empêchant l'interface Selkies de se charger.
    *   **Analyse :**
        1.  Le **Symptôme 1** est causé par une logique obsolète dans `aikore/static/app.js`. Le code génère toujours une URL de type reverse proxy au lieu d'une URL d'accès direct utilisant le `persistent_port` de l'instance.
        2.  Le **Symptôme 2** est probablement une conséquence du premier ou un problème distinct. Le fait que même l'accès direct échoue suggère que l'interaction entre le client web Selkies et son serveur est perturbée. La priorité absolue est de corriger la génération de l'URL pour éliminer la première source d'erreur.
    *   **Correction Critique Identifiée :** Il a été découvert que le thread de monitoring (`monitor_instance_thread` dans `process_manager.py`) lançait le navigateur Firefox interne en le faisant pointer sur le port de Selkies au lieu du port de l'application. Cela a été corrigé.

### 6.4. Plan d'Action pour la Prochaine Session

*   **Priorité 1 : Corriger la génération d'URL dans le frontend.**
    *   Modifier les fonctions `renderInstanceRow` et `updateInstanceRow` dans `aikore/static/app.js` pour qu'elles construisent l'URL d'accès direct (`//<hostname>:<persistent_port>/`) pour les instances où `persistent_mode` est `true`.

*   **Priorité 2 : Re-tester la connexion de bout en bout.**
    *   Après la correction du frontend, créer une nouvelle instance persistante et vérifier que le bouton "Open" redirige vers la bonne URL et que la connexion s'établit avec succès.

*   **Priorité 3 : Implémenter la fonctionnalité "Update".**
    *   Créer l'endpoint API et la logique de base de données pour la mise à jour d'une instance existante.