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
    | `status`             | STRING          | État actuel : 'stopped', 'starting', 'stalled', 'started', 'error'.         |
    | `pid`                | INTEGER         | Process ID du processus principal de l'instance.                            |
    | `port`               | INTEGER         | Port interne de l'application (toujours utilisé, souvent éphémère).         |
    | `persistent_port`    | INTEGER         | Port exposé à l'utilisateur pour l'interface KasmVNC. Utilisé si `persistent_mode` est vrai. |
    | `persistent_display` | INTEGER         | Numéro de l'affichage X11 virtuel utilisé par la session KasmVNC.           |
    
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
    │   │   ├── 📁 welcome/            # Contient les ressources pour l'écran d'accueil animé.
    │   │   │   ├── 📁 js/             # Scripts JavaScript pour l'animation.
    │   │   │   │   ├── - effects.js  # Définit les effets visuels de l'animation (ex: l'effet de vague).
    │   │   │   │   ├── - main.js     # Point d'entrée principal de l'animation, gère la scène et le cycle de vie.
    │   │   │   │   └── - renderer.js # Gère le dessin de l'animation sur le canvas HTML.
    │   │   │   ├── 📁 logos/          # Fichiers texte contenant l'art ASCII du logo.
    │   │   │   └── - index.html & style.css # Structure et style de la page de l'animation.
    │   │   ├── - app.js              # Le cœur du frontend : gère toute la logique de l'interface (API calls, rendu du tableau, modales, logs, terminal...).
    │   │   ├── - index.html          # La structure HTML unique de la page principale de l'application.
    │   │   └── - style.css           # La feuille de style principale pour l'ensemble du tableau de bord.
    │   ├── - main.py                 # Point d'entrée de l'application FastAPI. Initialise l'app, les routes, et lance la migration de la DB au démarrage.
    │   └── - requirements.txt        # Liste des dépendances Python pour le backend AiKore.
    ├── 📁 blueprints/                # Collection de scripts "modèles" définissant comment installer et lancer chaque application d'IA.
    │   ├── 📁 legacy/               # Anciens scripts qui ne suivent pas la nouvelle convention des blueprints. Conservés pour référence.
    │   └── - *.sh                    # Chaque script est un "blueprint" autonome pour une application (ex: ComfyUI.sh).
    ├── 📁 docker/                    # Fichiers de configuration spécifiques à l'environnement Docker.
    │   └── 📁 root/                  # Contenu copié à la racine `/` du conteneur.
    │       └── 📁 etc/
    │           ├── 📁 nginx/conf.d/   # Configuration pour NGINX.
    │           │   └── - aikore.conf # Fichier principal de NGINX qui gère le reverse proxy.
    │           ├── 📁 s6-overlay/     # Scripts et configuration pour le superviseur de processus s6.
    │           └── 📁 sudoers.d/       # Fichiers de configuration pour les permissions `sudo`.
    ├── 📁 scripts/                   # Scripts utilitaires appelés par l'application ou les blueprints.
    │   └── - kasm_launcher.sh        # Script crucial qui orchestre le lancement d'une session KasmVNC (Xvnc, Openbox) pour les instances en mode persistant.
    ├── - .gitignore                  # Spécifie les fichiers que Git doit ignorer.
    ├── - context.md                  # Ce fichier. Documentation de haut niveau et mémoire de session.
    ├── - docker-compose.dev.yml      # Fichier Docker Compose pour l'environnement de développement.
    ├── - docker-compose.yml          # Fichier Docker Compose simplifié pour le déploiement.
    ├── - Dockerfile                  # Script de build principal pour l'image Docker finale d'AiKore.
    ├── - Dockerfile.buildbase        # Script pour l'image de base, contenant les compilations longues et les dépendances lourdes.
    ├── - entry.sh                    # Script principal exécuté par le conteneur pour lancer l'application AiKore.
    ├── - features.md                 # Suivi de l'implémentation des fonctionnalités du projet.
    ├── - functions.sh                # Bibliothèque de fonctions shell partagées (`sl_folder`, `sync_repo`) utilisées par les blueprints.
    ├── - GEMINI.md                   # Notes internes pour l'IA.
    ├── - Makefile                    # Raccourcis pour les commandes Docker (`make up`, `make down`).
    └── - plan.md                     # Document initial de vision et de planification du projet.
    ```
    
    ---
    
    ## 6. État Actuel et Plan d'Action
    
    ### 6.1. Fonctionnalités Implémentées (Snapshot)
    
    Le projet a atteint une maturité fonctionnelle significative. Les fonctionnalités clés incluent :
    *   **Gestion CRUD+U d'Instances :** Création, lecture, **mise à jour** et suppression d'instances.
    *   **Système de Migration de Base de Données :** Un mécanisme de migration automatique et sécurisé met à jour le schéma de la base de données au démarrage, gérant la sauvegarde, le transfert et la vérification des données.
    *   **Configuration Avancée des Instances :** Hostname personnalisé, sélection de GPU par checkboxes, et sélection de port à la création.
    *   **Lancement de Processus :** Démarrage et arrêt des instances.
    *   **Interface Web Réactive :** Tableau de bord multi-panneaux avec état et statistiques en temps réel.
    *   **Intégration de KasmVNC :** Les instances persistantes lancent un serveur KasmVNC autonome et isolé.
    *   **Outils Avancés :** Visionneuse de Logs, Éditeur de Script, Terminal Intégré, Vue Embarquée.
    *   **Reconstruction d'Environnement :** Une fonctionnalité UX complète pour reconstruire l'environnement Python d'une instance via l'interface.
    
    ### 6.2. Problèmes Connus et Points en Attente
    
    *   **Redémarrage Intempestif sur Mise à Jour :** La mise à jour de champs "non-disruptifs" comme le `hostname` (adresse personnalisée) provoque un redémarrage complet de l'instance. La logique de distinction a été ajoutée à `api/instances.py` mais son implémentation finale (rechargement de NGINX) dans `core/process_manager.py` est manquante ou incomplète.
    
    ### 6.3. Journal d'Investigation
    
    *   **Session du 2025-11-11 :**
        *   **Objectif :** Implémentation d'un chemin de sortie personnalisable et standardisation des blueprints.
        *   **Problèmes Résolus & Améliorations :**
            1.  **Implémentation du Chemin de Sortie Personnalisable :** Le champ "Output Path" permet de définir un dossier de sortie personnalisé sous `/config/outputs/`. Le backend passe le chemin complet via une variable d'environnement au blueprint.
            2.  **Sécurisation de la Mise à Jour du Chemin :** Un avertissement a été ajouté à l'interface pour informer l'utilisateur que le changement de chemin ne déplace pas les données existantes, prévenant ainsi toute perte accidentelle.
            3.  **Standardisation des Blueprints :** Correction des appels à la fonction `sl_folder` dans `ComfyUI.sh` pour utiliser la syntaxe standard à 4 arguments, améliorant la robustesse.
        *   **État à la fin de la session :** La fonctionnalité de chemin de sortie personnalisé est complète, sécurisée et intuitive.
    
    *   **Session du 2025-11-11 (Soir) :**
        *   **Objectif :** Résolution de trois bugs d'interface utilisateur (UI/UX).
        *   **Problèmes Résolus & Améliorations :**
            1.  **Correction du bug d'affichage multi-GPU :** La logique de rendu dans `app.js` a été rendue plus robuste. Elle inspecte désormais la structure de données des GPUs retournée par l'API pour s'assurer que toutes les cartes graphiques disponibles s'affichent correctement sous forme de cases à cocher, au lieu d'afficher "N/A".
            2.  **Correction du bug de perte de focus :** La boucle de rafraîchissement automatique dans `app.js` a été modifiée pour ne plus s'exécuter si l'utilisateur a le focus sur un champ de saisie dans *n'importe quelle* ligne de la table (y compris la ligne de création). Cela empêche la table de se redessiner et de voler le focus pendant la saisie.
        *   **Problèmes Non Résolus :**
            *   Le bug de redémarrage intempestif lors de la mise à jour du `hostname` persiste. Bien que la logique de distinction entre les mises à jour "sûres" et "disruptives" ait été implémentée dans `api/instances.py`, l'étape finale de rechargement de NGINX sans redémarrer l'instance n'est pas encore fonctionnelle.
        *   **État à la fin de la session :** L'interface est significativement plus stable et intuitive pour la création et la modification d'instances. Le dernier bug majeur identifié est localisé côté backend.
    
    ### 6.4. Plan d'Action pour la Prochaine Session
    
    *   **Priorité 1 :** Finaliser la correction du bug de redémarrage intempestif. Cela nécessitera d'inspecter et potentiellement de modifier `aikore/core/process_manager.py` pour implémenter une fonction `update_nginx_config` qui régénère le fichier de configuration NGINX et recharge le service sans interrompre les instances en cours d'exécution.
    *   **Priorité 2 :** Améliorer la gestion globale des erreurs en standardisant l'utilisation des notifications "toast" pour tous les retours d'API (succès et erreurs), afin de fournir un feedback utilisateur plus cohérent et moins intrusif.