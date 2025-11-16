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
            *   Le bug de redémarrage intempestif lors de la mise à jour du `hostname` persiste. Bien que la logique de distinction entre les mises à jour "sûres" et "disruptives` ait été implémentée dans `api/instances.py`, l'étape finale de rechargement de NGINX sans redémarrer l'instance n'est pas encore fonctionnelle.
        *   **État à la fin de la session :** L'interface est significativement plus stable et intuitive pour la création et la modification d'instances. Le dernier bug majeur identifié est localisé côté backend.
    
    ### 6.4. Plan d'Action pour la Prochaine Session
    
    *   **Priorité 1 :** Finaliser la correction du bug de redémarrage intempestif. Cela nécessitera d'inspecter et potentiellement de modifier `aikore/core/process_manager.py` pour implémenter une fonction `update_nginx_config` qui régénère le fichier de configuration NGINX et recharge le service sans interrompre les instances en cours d'exécution.
    *   **Priorité 2 :** Améliorer la gestion globale des erreurs en standardisant l'utilisation des notifications "toast" pour tous les retours d'API (succès et erreurs), afin de fournir un feedback utilisateur plus cohérent et moins intrusif.
    
---

## 7. Nouvelles Fonctionnalités : Copie et Instanciation d'Instances

### 7.1. Fonctionnalité "Copie" (Duplication d'Instance)

Cette fonctionnalité permet de créer un clone parfait et totalement indépendant d'une instance existante. La nouvelle instance aura sa propre configuration, son propre environnement virtuel et ses propres dossiers, initialisés avec les mêmes valeurs que l'original.

#### Plan d'implémentation :

**1. Backend - API (`aikore/api/instances.py`)**

*   **Nouvelle route d'API :** `POST /api/instances/{id}/copy`
    *   Prend l'ID de l'instance à copier.
    *   Attend en entrée le nom de la nouvelle instance : `{ "new_name": "..." }`.

**2. Logique Principale (`aikore/database/crud.py`)**

*   **Nouvelle fonction :** `copy_instance(db: Session, source_instance_id: int, new_name: str)`
    *   **Étape 1 (Validation) :** Vérifier que le `new_name` n'est pas déjà utilisé.
    *   **Étape 2 (Base de données) :**
        *   Lire les données de l'instance source.
        *   Créer une nouvelle entrée pour le clone en copiant les champs suivants de la source :
            *   `base_blueprint`
            *   `gpu_ids`
            *   `autostart`
            *   `persistent_mode`
            *   `output_path` (Le chemin de sortie est conservé)
            *   `hostname` (L'adresse custom est conservée)
        *   Définir les champs spécifiques pour le clone :
            *   `name` = `new_name`
            *   `status` = `"stopped"`
            *   `use_custom_hostname` = `False` (L'adresse custom est désactivée)
            *   Les champs `pid`, `port`, `persistent_port`, etc., sont laissés à `NULL`.
        *   Sauvegarder la nouvelle instance.
    *   **Étape 3 (Dossiers) :** Copier le dossier de configuration de la source vers le nouveau dossier du clone.
    *   **Étape 4 (Environnement Conda) :** Exécuter `conda create --prefix /path/to/new/env --clone /path/to/source/env`.
    *   **Étape 5 (Mise à jour du script) :** Modifier le `launch.sh` du clone pour qu'il utilise le chemin du nouvel environnement.
    *   **Étape 6 (Retour) :** Renvoyer l'objet de la nouvelle instance.

**3. Frontend (`aikore/static/app.js` et `aikore/static/index.html`)**

*   **Activer le bouton "Clone"** dans le menu contextuel des instances.
*   **Ajouter un gestionnaire d'événement :**
    *   Au clic sur "Clone", demander le nom de la nouvelle instance.
    *   Envoyer la requête `POST` à l'API.
    *   Après une réponse positive, rafraîchir la liste des instances.

### 7.2. Fonctionnalité "Instancier" (Référencement d'Instance)

Cette fonctionnalité permet de créer une instance "satellite" ou "liée" qui partage le script et l'environnement Conda d'une instance "mère", tout en ayant ses propres paramètres d'exécution (Output Path, GPU, Autostart, Persistent Mode, Custom Address, Port).

#### Plan d'implémentation :

**1. Base de Données (`aikore/database/models.py`)**

*   **Ajouter une colonne à la table `Instance` :**
    *   `parent_instance_id = Column(Integer, nullable=True)`
    *   Cette colonne contiendra l'ID de l'instance "mère". Si elle est `NULL`, c'est une instance normale/mère.

**2. Backend - API (`aikore/api/instances.py`)**

*   **Nouvelle route d'API :** `POST /api/instances/{id}/instantiate`
    *   Prend l'ID de l'instance mère.
    *   Attend en entrée le nom de la nouvelle instance satellite : `{ "new_name": "..." }`.

**3. Logique Principale (`aikore/database/crud.py`)**

*   **Nouvelle fonction :** `instantiate_instance(db: Session, parent_instance_id: int, new_name: str)`
    *   **Étape 1 (Validation) :** Vérifier que le `new_name` n'est pas déjà utilisé.
    *   **Étape 2 (Base de données) :**
        *   Lire les données de l'instance mère.
        *   Créer une nouvelle entrée pour l'instance satellite.
        *   **Définir les liens et le statut :**
            *   `name` = `new_name`
            *   `parent_instance_id` = `parent_instance_id` (l'ID de la mère)
            *   `status` = `"stopped"`
        *   **Copier les paramètres de la mère comme base pour le satellite (ce seront ses propres valeurs modifiables) :**
            *   `base_blueprint`
            *   `output_path`
            *   `gpu_ids`
            *   `autostart`
            *   `persistent_mode`
            *   `hostname` et `use_custom_hostname`
        *   **Réinitialiser les valeurs d'exécution :** `pid`, `port`, etc., à `NULL`.
        *   Sauvegarder la nouvelle instance satellite.
    *   **Étape 3 (Système de fichiers) :** Aucune opération. Pas de copie de dossier, pas de création d'environnement.

**4. Logique de Démarrage (`aikore/core/process_manager.py`)**

*   **Modifier la fonction `start_instance` :**
    *   Au début, vérifier si `instance.parent_instance_id` n'est pas `NULL`.
    *   Si c'est un satellite :
        1.  Charger l'instance mère depuis la base de données.
        2.  Déterminer le chemin du dossier de configuration et de l'environnement Conda en se basant sur l'instance **mère**.
        3.  Lancer le `launch.sh` qui se trouve dans le dossier de la **mère**.
        4.  Utiliser les paramètres (`gpu_ids`, `port`, etc.) de l'instance **satellite** pour configurer les variables d'environnement du processus.

**5. Frontend (`aikore/static/app.js` et `aikore/static/index.html`)**

*   **Ajouter un bouton "Instancier"** dans le menu.
*   **Au clic :** Demander le nom, appeler l'API, et rafraîchir la liste.
*   **Adapter l'affichage :**
    *   Regrouper visuellement les satellites sous leur mère (indentation, ligne de connexion).
    *   Pour une instance satellite, **griser/désactiver** les contrôles qui modifient les ressources partagées (ex: le bouton "Éditer le script", le choix du blueprint).
    *   S'assurer que les contrôles pour les paramètres indépendants (`Output Path`, `GPU`, `Autostart`, `Persistent`, `Custom Address`, `Port`) sont **actifs et modifiables**.

### 6.5. Journal d'Investigation (Suite)

*   **Session du 2025-11-15 :**
    *   **Objectif :** Implémentation de la fonctionnalité "Instancier" (instances satellites).
    *   **Problèmes Résolus & Améliorations :**
        1.  **Modification du Schéma de DB :** Ajout de la colonne `parent_instance_id` à la table `Instance` pour créer la relation parent-enfant.
        2.  **Migration de la DB :** Création d'un script de migration (v4 vers v5) pour ajouter la nouvelle colonne de manière non destructive.
        3.  **Backend Complet :** Implémentation de la route d'API `POST /api/instances/{id}/instantiate` et de la logique CRUD `instantiate_instance` correspondante.
        4.  **Mise à jour du Process Manager :** La fonction `start_instance_process` a été modifiée pour gérer les instances satellites. Elle utilise désormais le script et l'environnement de l'instance parente tout en appliquant les paramètres d'exécution (GPU, port, etc.) du satellite.
        5.  **Interface Utilisateur :** Le frontend a été mis à jour pour permettre l'instanciation via le menu contextuel. La logique de rendu a été modifiée pour afficher les instances de manière hiérarchique (parents et enfants indentés).
        6.  **Correction de Bug :** Résolution d'une `NameError` dans `api/instances.py` due à une importation incorrecte du module `schemas`.
    *   **État à la fin de la session :** La fonctionnalité "Instancier" est entièrement implémentée, du backend au frontend.

### 6.6. Nouveaux Problèmes Identifiés

*   **Bug - Rendu de l'Instanciation :** Il n'y a pas de ligne ou de repère visuel clair connectant une instance satellite à son parent, l'indentation seule peut ne pas être suffisante.
*   **Bug - Contrôles de l'Instanciation :** Les contrôles de l'interface utilisateur (par exemple, le sélecteur de blueprint) ne sont pas correctement désactivés pour les instances satellites, ce qui pourrait prêter à confusion.
*   **Bug - Contexte d'Exécution des Outils :** Les outils comme le terminal, lorsqu'ils sont lancés depuis une instance satellite, tentent de s'exécuter dans le dossier de configuration vide du satellite au lieu de celui du parent, ce qui les rend non fonctionnels.
*   **Bug - Clonage Incomplet :** La fonctionnalité "Clone" ne copie actuellement que le dossier de l'environnement (`env`) et non les autres fichiers de configuration, ce qui rend le clone inutilisable.
---

## 8. Session du 2025-11-16

### 8.1. Objectifs de la session

*   Vérifier et standardiser les installations de PyTorch.
*   Refactoriser le frontend (CSS et JavaScript) pour améliorer la maintenabilité.
*   Corriger les bugs introduits par la refactorisation.

### 8.2. Actions et Résolutions

1.  **Standardisation de PyTorch :**
    *   Une recherche a été effectuée pour s'assurer que toutes les installations de `torch` et `torchvision` utilisaient l'index CUDA 13.0 (`--index-url https://download.pytorch.org/whl/cu130`).
    *   Il a été constaté que les `Dockerfile` principaux étaient corrects.
    *   Suite à la clarification de l'utilisateur, les scripts "legacy" ont été ignorés.
    *   Le blueprint `ComfyUI.sh` a été modifié pour installer explicitement `torch` et `torchvision` au lieu de dépendre de wheels pré-compilés, conformément à la demande de l'utilisateur.

2.  **Refactorisation du Frontend :**
    *   **CSS :** Le fichier monolithique `style.css` a été divisé en cinq fichiers plus petits et spécialisés (`base.css`, `instances.css`, `modals.css`, `components.css`, `tools.css`) et placés dans un nouveau répertoire `aikore/static/css/`.
    *   **JavaScript :** Le fichier `app.js` de plus de 1000 lignes a été entièrement refactorisé en une architecture modulaire (ESM) dans le nouveau répertoire `aikore/static/js/`. Les responsabilités ont été réparties entre `state.js`, `api.js`, `ui.js`, `modals.js`, `tools.js`, `eventHandlers.js`, et un point d'entrée `main.js`.
    *   Le fichier `index.html` a été mis à jour pour charger les nouveaux fichiers CSS et le module JavaScript principal.

3.  **Débogage Post-Refactorisation :**
    *   **Bug d'affichage majeur :** Un bug bloquant l'affichage a été signalé. L'analyse a révélé des **dépendances circulaires** en JavaScript (ex: `main.js` important `api.js` qui importait `main.js`).
    *   **Correction Architecturale :** La correction a consisté à redéfinir les responsabilités des modules. `api.js` a été rendu "aveugle" à l'interface, se contentant de retourner les résultats des appels serveur. Les modules d'UI (`eventHandlers.js`, `modals.js`) ont été modifiés pour attendre (`await`) les réponses de l'API avant de déclencher eux-mêmes les mises à jour de l'affichage.
    *   **Bug des outils (Logs/Éditeur) :** Il a été découvert que la visionneuse de logs et l'éditeur de script ne s'affichaient plus. Deux bugs ont été identifiés et corrigés dans `tools.js` :
        1.  Un appel à la fonction `fetchLogs` sans le paramètre `offset` requis.
        2.  L'éditeur de code recevait un objet `{content: "..."}` au lieu de la chaîne de caractères attendue.
    *   **Bug du bouton "Ouvrir" :** L'URL générée pour le bouton "Ouvrir" pointait vers le lien interne du reverse proxy au lieu de l'adresse directe `host:port`. La fonction `buildInstanceUrl` dans `ui.js` a été corrigée pour faire la distinction entre une "Vue" interne et une "Ouverture" externe.

4.  **Vérification gRPC :**
    *   Une recherche a confirmé que gRPC n'est pas utilisé dans le projet.

### 8.3. État à la fin de la session

Le frontend a été entièrement refactorisé avec une architecture modulaire plus saine et robuste. Les bugs critiques introduits par cette refactorisation ont été identifiés et corrigés. L'application est de nouveau dans un état fonctionnel et stable, avec une base de code frontend significativement améliorée pour la maintenance future.
