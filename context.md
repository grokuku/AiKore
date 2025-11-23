### 1. Vision et Objectifs du Projet
    
    **Mission :** Transformer un ensemble de scripts de gestion d'outils d'IA en **AiKore**, une plateforme de gestion unifiée, accessible via une interface web, pour lancer, administrer et superviser des applications (WebUIs) d'intelligence artificielle.
    
    L'objectif principal est de fournir un panneau de contrôle unique, simple et puissant, qui abstrait la complexité de la configuration manuelle. AiKore vise à offrir une expérience robuste et conviviale, particulièrement pour la gestion de tâches de longue durée (entraînement, génération) ou de configurations multi-GPU.
    
    ---
    
    ## 2. Principes d'Architecture Fondamentaux
    
    1.  **Conteneur Docker Unique :** L'intégralité du système (backend, frontend, reverse proxy) et tous les processus des applications d'IA tournent au sein d'un unique conteneur Docker pour une simplicité d'installation maximale.
    2.  **Gestion Dynamique par Instances :** Le système est passé d'une configuration statique (un dossier par application) à un modèle dynamique où les utilisateurs peuvent créer, configurer et gérer de multiples "instances" indépendantes de n'importe quelle application via des "blueprints".
    3.  **Interface Web Centralisée :** Toutes les opérations de gestion courantes sont effectuées via l'interface web. Aucune modification manuelle de fichiers de configuration n'est requise pour l'utilisation standard.
    4.  **Base de Données pour la Persistance :** Les configurations des instances sont stockées dans une base de données SQLite, garantissant leur persistance entre les redémarrages du conteneur.
    5.  **Accès aux Instances :** L'accès utilisateur final se fait selon trois modes distincts :
        *   **Mode Proxy NGINX :** Pour les instances standards sans nom d'hôte personnalisé. L'accès se fait via une URL relative (`/instance/<nom_instance>/`), et NGINX route les requêtes vers le port interne de l'application.
        *   **Mode Hostname Personnalisé :** Si `use_custom_hostname` est activé, l'accès se fait via l'URL absolue définie dans le champ `hostname` (ex: `http://mon-app.local`).
        *   **Mode Persistant (KasmVNC) :** L'instance est directement exposée sur un port dédié du conteneur (ex: 19001), et l'accès se fait via `http://<hôte_aikore>:<port_persistant>`. NGINX n'est pas utilisé pour ce mode.
    6.  **Mode d'Interface Persistante (KasmVNC) :** Pour les applications nécessitant une session de bureau graphique persistante, AiKore utilise **KasmVNC**.
    
    ---
    
    ## 3. Architecture et Technologies
    
    *   **Orchestration :** Docker, s6-overlay
    *   **Backend API :** FastAPI (Python)
    *   **Serveur Applicatif :** Uvicorn (pour FastAPI), NGINX (comme reverse proxy)
    *   **Frontend :** SPA (Single Page Application) en HTML, CSS, JavaScript (vanilla)
    *   **Base de Données :** SQLite (via SQLAlchemy)
    *   **Migration de Schéma :** Un script de migration automatisé est intégré au démarrage de l'application.
    *   **Gestion des Processus :** Le module `subprocess` de Python, géré par `process_manager.py`.
    *   **Terminal Interactif :** `xterm.js` côté frontend, `pty` côté backend.
    *   **Éditeur de Code :** CodeMirror
    *   **Interface Persistante :** KasmVNC (Xvnc, Openbox)
    
    ---
    
    ## 4. Modèle de Données (Table `instances`, Schéma v4)
    
    | Nom de la Colonne     | Type de Données | Description                                                                 |
    |----------------------|-----------------|-----------------------------------------------------------------------------|
    | `id`                 | INTEGER         | Clé primaire.                                                               |
    | `name`               | STRING          | Nom unique défini par l'utilisateur pour l'instance.                         |
    | `base_blueprint`     | STRING          | Nom du fichier script de base (ex: "ComfyUI.sh").                           |
    | `gpu_ids`            | STRING          | Chaîne de caractères des ID de GPU (ex: "0,1"), passée à `CUDA_VISIBLE_DEVICES`. |
    | `autostart`          | BOOLEAN         | Si `true`, l'instance est lancée au démarrage d'AiKore.                     |
    | `persistent_mode`    | BOOLEAN         | Si `true`, l'instance est lancée dans une session de bureau KasmVNC.        |
    | `hostname`           | STRING          | **(V2)** Hostname/URL personnalisé pour l'accès direct à l'instance.      |
    | `use_custom_hostname`| BOOLEAN         | **(V3)** Si `true`, le `hostname` est utilisé pour construire l'URL d'accès. |
    | `output_path`        | STRING          | **(V4)** Nom du dossier de sortie sous `/config/outputs/`.                  |
    | `status`             | STRING          | État actuel : 'stopped', 'starting', 'stalled', 'started', 'error', 'installing'. |
    | `pid`                | INTEGER         | Process ID du processus principal de l'instance.                            |
    | `port`               | INTEGER         | Port interne de l'application (toujours utilisé, souvent éphémère).         |
    | `persistent_port`    | INTEGER         | Port exposé à l'utilisateur pour l'interface KasmVNC. Utilisé si `persistent_mode` est vrai. |
    | `persistent_display` | INTEGER         | Numéro de l'affichage X11 virtuel utilisé par la session KasmVNC.           |
    | `parent_instance_id` | INTEGER         | **(V5)** ID de l'instance parente (pour les instances satellites).          |
    
    ---
    
    ## 5. Arborescence Détaillée du Projet
    
    ```
    .
    ├── 📁 aikore/                     # Racine du code source de l'application Python AiKore.
    │   ├── 📁 api/                   # Contient les modules définissant les endpoints de l'API FastAPI.
    │   │   ├── - __init__.py         # Marqueur de package Python.
    │   │   ├── - instances.py        # Gère toutes les routes API liées aux instances (CRUD, start/stop, logs, terminal...).
    │   │   └── - system.py           # Gère les routes API liées au système (infos GPU, stats, liste des blueprints...).
    │   ├── 📁 core/                  # Cœur de la logique métier de l'application.
    │   │   ├── - __init__.py         # Marqueur de package Python.
    │   │   └── - process_manager.py  # Le "cerveau" : gère le cycle de vie des processus (démarrage, arrêt, monitoring), la création des PTY pour le terminal, et la gestion des fichiers de configuration NGINX.
    │   ├── 📁 database/              # Module pour l'interaction avec la base de données.
    │   │   ├── - __init__.py         # Marqueur de package Python.
    │   │   ├── - crud.py             # Fonctions "Create, Read, Update, Delete" pour manipuler les objets de la base de données.
    │   │   ├── - migration.py        # Script crucial qui gère la migration du schéma de la base de données entre les versions.
    │   │   ├── - models.py           # Définition des modèles de tables SQLAlchemy (ex: la table "Instance").
    │   │   └── - session.py          # Configuration et initialisation de la connexion à la base de données SQLite.
    │   ├── 📁 schemas/               # Modèles de données Pydantic pour la validation des requêtes et réponses de l'API.
    │   │   ├── - __init__.py         # Marqueur de package Python.
    │   │   └── - instance.py         # Définit les schémas pour la création, la mise à jour et la lecture des données d'instance.
    │   ├── 📁 static/                # Fichiers statiques du frontend (servis directement au navigateur).
    │   │   ├── 📁 js/                # Scripts JavaScript modulaires (ESM).
    │   │   │   ├── - api.js          # Communication avec le backend.
    │   │   │   ├── - ui.js           # Rendu de l'interface (tableaux, stats).
    │   │   │   ├── - eventHandlers.js# Gestion des clics et interactions.
    │   │   │   ├── - tools.js        # Gestion des outils (terminal, éditeur).
    │   │   │   ├── - modals.js       # Gestion des fenêtres modales.
    │   │   │   └── - main.js         # Point d'entrée.
    │   │   └── - index.html          # La structure HTML unique de la page principale.
    │   ├── - main.py                 # Point d'entrée de l'application FastAPI. Initialise l'app, les routes, et lance la migration de la DB au démarrage.
    │   └── - requirements.txt        # Liste des dépendances Python pour le backend AiKore.
    ├── 📁 blueprints/                # Collection de scripts "modèles" définissant comment installer et lancer chaque application d'IA.
    │   ├── 📁 legacy/               # Anciens scripts qui ne suivent pas la nouvelle convention des blueprints. Conservés pour référence.
    │   └── - *.sh                    # Chaque script est un "blueprint" autonome pour une application (ex: ComfyUI.sh).
    ├── 📁 docker/                    # Fichiers de configuration spécifiques à l'environnement Docker.
    │   └── 📁 root/                  # Contenu copié à la racine `/` du conteneur.
    ├── 📁 scripts/                   # Scripts utilitaires appelés par l'application ou les blueprints.
    │   └── - kasm_launcher.sh        # Script crucial qui orchestre le lancement d'une session KasmVNC (Xvnc, Openbox) pour les instances en mode persistant.
    ├── - context.md                  # Ce fichier. Documentation de haut niveau et mémoire de session.
    ├── - docker-compose.yml          # Fichier Docker Compose simplifié pour le déploiement.
    ├── - Dockerfile                  # Script de build principal pour l'image Docker finale d'AiKore.
    └── - features.md                 # Suivi de l'implémentation des fonctionnalités du projet.
    ```
    
    ---
    
    ## 6. État Actuel et Plan d'Action
    
    ### 6.1. Fonctionnalités Implémentées (Snapshot)
    
    *   **Gestion CRUD+U d'Instances :** Création, lecture, **mise à jour** et suppression d'instances.
    *   **Architecture Parent/Satellite :** Instanciation d'environnements liés.
    *   **Mode Persistant (KasmVNC) :** Bascule dynamique entre mode API (headless) et mode Bureau (VNC).
    *   **Système de Migration de Base de Données :** Mise à jour automatique du schéma.
    *   **Interface Web Réactive :** Tableau de bord modulaire et temps réel.
    *   **Outils Avancés :** Visionneuse de Logs, Éditeur de Script, Terminal Intégré.
    *   **Auto-Réparation :** Le système détecte et répare les configurations de ports invalides au démarrage d'une instance.
    
    ### 6.2. Problèmes Connus et Points en Attente
    
    *   *(Aucun problème critique bloquant identifié à la fin de la dernière session)*
    
    ### 6.3. Journal d'Investigation
    
    *   **Session du 2025-11-23 : Stabilisation UI & Logique de Ports**
        *   **Objectifs :** Corriger les bugs d'affichage suite au refactoring, réparer l'assignation des GPU, et fiabiliser la bascule entre mode Normal et Persistant.
        *   **Corrections UI (Frontend) :**
            1.  **Bug Colonnes :** Correction de l'index de colonne dans `ui.js` qui écrasait "Custom Address" avec le port.
            2.  **Bug Duplication :** Correction dans `eventHandlers.js` pour supprimer la ligne temporaire de création après une sauvegarde réussie.
            3.  **Gestion des Erreurs API :** Mise à jour de `api.js` pour gérer les réponses d'erreur non-JSON (ex: 500 Internal Server Error) et afficher le vrai message d'erreur.
            4.  **Affichage du Port :** Refonte de la colonne Port pour afficher un menu déroulant intelligent, sélectionnant automatiquement le "Port Public" actif et supprimant l'option "Auto" pour les instances existantes.
        *   **Corrections Backend (API & Core) :**
            1.  **Assignation GPU :** Ajout de `CUDA_DEVICE_ORDER="PCI_BUS_ID"` dans `process_manager.py` pour garantir que l'ordre des cartes correspond à la sélection de l'interface.
            2.  **Crash API (TypeError) :** Correction d'un bug critique dans `update_instance_details` où la vérification de plage de ports plantait si le port était `None`.
            3.  **Logique de Bascule (Switch Mode) :** Réécriture complète de la logique de mise à jour pour gérer correctement le transfert du "Port Public" entre `port` (Mode Normal) et `persistent_port` (Mode Persistant), en évitant la perte de configuration.
            4.  **Auto-Réparation (Self-Healing) :** Implémentation d'une sécurité dans `start_instance` (`api/instances.py`) qui détecte les instances avec des ports manquants (ex: suite à un échec précédent) et les répare automatiquement avant le démarrage.
            5.  **Sécurité Processus :** Ajout de gardes-fous dans `process_manager.py` pour empêcher le lancement de processus avec des ports `None`.
    
    *   **Session du 2025-11-19 :**
        *   **Optimisations :** Accélération du démarrage du conteneur (permissions chown) et refonte du clonage en tâche de fond asynchrone.
        *   **Sécurité :** Protection contre la suppression d'instances Mères ayant des Satellites.
    
    ### 6.4. Plan d'Action pour la Prochaine Session
    
    *   **Validation Utilisateur :** Confirmer que la bascule de mode et l'auto-réparation fonctionnent comme attendu sur l'instance "Comfytest".
    *   **Documentation :** Mettre à jour le `features.md` si de nouvelles capacités ont été ajoutées (ex: Self-Healing).
    *   **UX Satellites :** Améliorer la visualisation du lien parent-enfant (arborescence visuelle plus claire).
    
---