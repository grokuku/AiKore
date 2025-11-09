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

## 4. Modèle de Données (Table `instances`, Schéma v3)

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

*   La logique d'interaction entre les boutons "Update Instance" et "Save as Custom Blueprint" dans l'éditeur de script n'est pas finalisée et a conduit à des comportements inattendus. Le développement de cette micro-fonctionnalité est en pause.

### 6.3. Journal d'Investigation

*   **Session du 2025-11-07 :**
    *   **Objectif :** Implémenter la fonctionnalité de mise à jour des instances.
    *   **Défi Majeur :** L'ajout de nouveaux champs à la base de données a nécessité la création d'un système de migration de schéma robuste pour éviter la corruption des données existantes.
    *   **Problèmes Résolus :**
        1.  **Mise en Place d'un Système de Migration de DB :** Un script de migration versionné, automatique et sécurisé a été intégré au démarrage de l'application.
        2.  **Implémentation de la Mise à Jour :** L'API a été enrichie avec un endpoint `PUT /api/instances/{id}` et le frontend a été mis à jour pour permettre la modification et la sauvegarde des instances existantes.
        3.  **Améliorations UX :** Ajout de la gestion du `hostname` personnalisé, des checkboxes pour les GPU et de la sélection de port à la création.
        4.  **Correction de Bugs Frontend :** Résolution du bug qui faisait disparaître la ligne de création lors du rafraîchissement automatique du tableau.
    *   **État à la fin de la session :** Le système est stable. La fonctionnalité de mise à jour est complète et la base de données est maintenant versionnée, prête pour de futures évolutions.

*   **Session du 2025-11-09 :**
    *   **Objectif :** Correction de bugs d'interface et amélioration de l'expérience utilisateur (UX).
    *   **Problèmes Résolus :**
        1.  **Correction du bug d'alignement** sur la ligne "Nouvelle Instance" en ajustant le nombre de placeholders dans `app.js`.
        2.  **Activation et amélioration de la fonctionnalité 'Rebuild Environment' :**
            *   Implémentation d'une logique de confirmation conditionnelle (message différent si l'instance est active ou arrêtée).
            *   Modification du backend (`process_manager.py`) pour ne redémarrer l'instance que si elle était initialement active.
            *   Remplacement de l'alerte native du navigateur par une fenêtre modale personnalisée et stylisée.
            *   Remplacement de la notification `alert()` de confirmation par un système de "toast" non-bloquant pour un meilleur retour utilisateur.
            *   Correction d'une erreur de logique (`instanceToRebuild is null`) qui provoquait une exception lors de la confirmation.
        3.  **Vérification du Blueprint :** Analyse et validation de la logique de lien symbolique (`ln -sfn`) pour le dossier `output` dans le blueprint `ComfyUI.sh`, confirmant sa robustesse.
    *   **État à la fin de la session :** L'interface utilisateur est plus stable et l'expérience utilisateur a été significativement améliorée. La fonctionnalité de reconstruction d'environnement est maintenant complète, robuste et intuitive.

*   **Session du 2025-11-09 (Soir) :**
    *   **Objectif :** Refonte complète de la fonctionnalité d'édition de scripts pour améliorer l'ergonomie et ajouter des fonctionnalités avancées.
    *   **Problèmes Résolus & Améliorations :**
        1.  **Implémentation de la Coloration Syntaxique :** Remplacement du `<textarea>` basique par l'éditeur de code **CodeMirror**, configuré pour le `shell` avec un thème sombre, améliorant drastiquement la lisibilité des scripts.
        2.  **Rationalisation de l'Interface de l'Éditeur :** Suppression du bouton "Exit" redondant et refonte des actions de sauvegarde pour plus de clarté.
        3.  **Création de Blueprints Personnalisés :**
            *   Mise en place d'une nouvelle logique backend pour permettre aux utilisateurs de sauvegarder un script modifié en tant que nouveau **blueprint réutilisable**.
            *   Ces blueprints customs sont stockés dans un dossier persistant (`/config/custom_blueprints`) pour survivre aux mises à jour du conteneur, une décision d'architecture clé pour la robustesse.
        4.  **Amélioration de l'UX de Création :** La liste déroulante des blueprints dans le formulaire de création d'instance sépare maintenant visuellement les blueprints "Stock" des blueprints "Custom", rendant la sélection plus intuitive.
        5.  **Amélioration des Retours Utilisateur :** Remplacement des alertes JavaScript bloquantes par le système de notifications "toast" pour toutes les actions de l'éditeur, offrant un feedback plus fluide et cohérent.
    *   **État à la fin de la session :** La fonctionnalité d'édition est passée d'un simple outil de modification à une puissante fonctionnalité de gestion de templates, augmentant la flexibilité et la personnalisation d'AiKore.

*   **Session du 2025-11-09 (Soirée) :**
    *   **Objectif :** Améliorer l'ergonomie et corriger un bug critique dans la fonctionnalité d'édition de script.
    *   **Problèmes Résolus :**
        1.  **Correction du Bug Critique d'Écrasement :** Modification de `core/process_manager.py` pour que `start_instance_process` ne copie plus le contenu du blueprint si un `launch.sh` personnalisé existe déjà, préservant ainsi les modifications de l'utilisateur.
        2.  **Mise à jour du Backend :** Le schéma de mise à jour (`schemas/instance.py`) a été modifié pour autoriser le changement du `base_blueprint` d'une instance existante via l'API, une condition nécessaire pour une gestion correcte dans le frontend.
    *   **Points en Attente :**
        *   Le comportement souhaité pour l'interaction entre les boutons "Update Instance" et "Save as Custom Blueprint" a fait l'objet de plusieurs itérations sans aboutir à une solution satisfaisante.
        *   La décision a été prise de mettre cette amélioration en pause et de revenir à un fonctionnement simple et découplé : chaque bouton n'a qu'une seule fonction. L'implémentation de cette logique simplifiée reste à valider.

### 6.4. Plan d'Action pour la Prochaine Session

*   **Priorité 1 :** Valider l'implémentation de la logique simplifiée et découplée pour les boutons "Update Instance" et "Save as Custom Blueprint" dans l'éditeur de script. S'assurer que le comportement est clair, prévisible et sans effets de bord.
*   **Priorité 2 :** Améliorer la gestion globale des erreurs en standardisant l'utilisation des notifications "toast" pour tous les retours d'API (succès et erreurs), afin de fournir un feedback utilisateur plus cohérent et moins intrusif.