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
    *   **Mode Persistant (KasmVNC) :** L'instance est directement exposée sur un port dédié du conteneur (ex: 19001), défini par `AIKORE_INSTANCE_PORT_RANGE`. NGINX n'est pas utilisé pour ces instances.
6.  **Mode d'Interface Persistante (KasmVNC) :** Pour les applications nécessitant une session de bureau graphique persistante, AiKore utilise **KasmVNC**. Il lance une pile de bureau complète (`Xvnc`, `Openbox`) de manière isolée pour chaque instance concernée, permettant un accès distant via un navigateur web.

---

## 3. Architecture et Technologies

*   **Orchestration :** Docker, s6-overlay
*   **Backend API :** FastAPI (Python)
*   **Serveur Applicatif :** Uvicorn (pour FastAPI), NGINX (comme reverse proxy)
*   **Frontend :** SPA (Single Page Application) en HTML, CSS, JavaScript (vanilla)
*   **Base de Données :** SQLite (via SQLAlchemy)
*   **Gestion des Processus :** Le module `subprocess` de Python, géré par `process_manager.py`.
*   **Terminal Interactif :** `xterm.js` côté frontend, `pty` côté backend.
*   **Interface Persistante :** KasmVNC (Xvnc, Openbox)

---

## 4. Modèle de Données (Table `instances`)

| Nom de la Colonne     | Type de Données | Description                                                                 |
|----------------------|-----------------|-----------------------------------------------------------------------------|
| `id`                 | INTEGER         | Clé primaire.                                                               |
| `name`               | STRING          | Nom unique défini par l'utilisateur pour l'instance.                         |
| `base_blueprint`     | STRING          | Nom du fichier script de base (ex: "ComfyUI.sh").                           |
| `gpu_ids`            | STRING          | Chaîne de caractères des ID de GPU (ex: "0,1"), passée à `CUDA_VISIBLE_DEVICES`. |
| `autostart`          | BOOLEAN         | Si `true`, l'instance est lancée au démarrage d'AiKore.                     |
| `persistent_mode`    | BOOLEAN         | Si `true`, l'instance est lancée dans une session de bureau KasmVNC.        |
| `status`             | STRING          | État actuel : 'stopped', 'starting', 'stalled', 'started', 'error'.         |
| `pid`                | INTEGER         | Process ID du processus principal de l'instance.                            |
| `port`               | INTEGER         | Port interne de l'application (toujours utilisé, souvent éphémère).         |
| `persistent_port`    | INTEGER         | Port exposé à l'utilisateur pour l'interface KasmVNC. Utilisé si `persistent_mode` est vrai. |
| `persistent_display` | INTEGER         | Numéro de l'affichage X11 virtuel utilisé par la session KasmVNC.           |

---

## 5. Arborescence du Projet (avec descriptions)

```
📁 aikore/                     - Racine du code source de l'application Python.
    📁 api/                    - Contient les endpoints de l'API FastAPI.
    📁 core/                   - Logique métier principale.
        📄 process_manager.py  - Cœur de la gestion des instances (démarrage, arrêt, monitoring).
    📁 database/               - Tout ce qui concerne la base de données (modèles, CRUD, session).
    📁 schemas/                - Modèles Pydantic pour la validation des données de l'API.
    📁 static/                 - Fichiers servis directement au client (HTML, CSS, JS).
        📄 app.js              - Le cerveau du frontend, gère toute l'interactivité de la page.
        📄 index.html          - La page HTML unique de l'application.
        📄 style.css           - Styles CSS principaux.
    📄 main.py                 - Point d'entrée de l'application FastAPI.
    📄 requirements.txt        - Dépendances Python de l'application.

📁 blueprints/                 - Collection de scripts shell définissant comment installer et lancer chaque application d'IA.
    📄 ComfyUI.sh            - Exemple de blueprint pour ComfyUI.

📁 docker/                     - Fichiers de configuration spécifiques à Docker.
    📁 root/                   - Contenu à copier à la racine du conteneur Docker.
        📁 etc/
            📁 nginx/          - Configuration de NGINX.
            📁 s6-overlay/     - Scripts et configuration pour le superviseur de processus s6.
            📁 sudoers.d/      - Fichiers de configuration pour les permissions `sudo`.
        📁 home/
            📁 abc/
                📁 .config/
                    📁 openbox/
                        📄 rc.xml - Fichier de configuration pour Openbox (gestionnaire de fenêtres VNC).

📁 scripts/                    - Scripts utilitaires appelés par l'application.
    📄 kasm_launcher.sh      - Script crucial qui orchestre le lancement d'une session KasmVNC (Xvnc, Openbox) et du blueprint.

📄 Dockerfile                  - Script de build principal pour l'image Docker finale.
📄 Dockerfile.buildbase        - Script pour l'image de base, contenant les compilations longues.
📄 docker-compose.dev.yml      - Configuration Docker Compose pour l'environnement de développement.
```

---

## 6. État Actuel et Plan d'Action

### 6.1. Fonctionnalités Implémentées (Snapshot)

Le projet est dans une phase avancée, avec un socle fonctionnel robuste. Les fonctionnalités clés incluent :
*   **Gestion CRUD d'Instances :** Création, lecture et suppression d'instances.
*   **Lancement de Processus :** Démarrage et arrêt des instances.
*   **Interface Web Réactive :** Tableau de bord multi-panneaux avec état et statistiques en temps réel.
*   **Intégration de KasmVNC :** Les instances persistantes lancent un serveur KasmVNC autonome et isolé.
*   **Redimensionnement Dynamique VNC :** L'affichage VNC est maintenant parfaitement adaptatif, que ce soit en mode embarqué ("View") ou en plein écran ("Open").
*   **Outils Avancés :** Visionneuse de Logs, Éditeur de Script, Terminal Intégré, Vue Embarquée.
*   **Fonctionnalités UX :** Menu d'Outils Contextuel, Corbeille, Persistance de l'UI.

### 6.2. Problèmes Connus et Points en Attente

*   **Fonctionnalité de Mise à Jour Non Implémentée :** Le bouton "Update" sur chaque ligne d'instance est actuellement un placeholder.

### 6.3. Journal d'Investigation

*   **Session du 2025-11-06 :**
    *   **Objectif :** Résoudre les problèmes de redimensionnement de l'affichage VNC pour les instances persistantes.
    *   **Problèmes Résolus :**
        1.  **Erreur de Build Docker :** Corrigé une erreur de build dans le `Dockerfile` liée à un répertoire `/home/abc` manquant dans la nouvelle image de base, en ajoutant une instruction `mkdir -p /home/abc`.
        2.  **Redimensionnement VNC :** Le bug de la vue embarquée a été définitivement résolu via une approche combinée :
            *   **`app.js` :** L'URL du bouton **"View"** a été modifiée pour utiliser le paramètre `?resize=remote`, demandant au serveur VNC d'ajuster sa résolution à la taille de l'iframe.
            *   **`app.js` :** L'URL du bouton **"Open"** a été corrigée pour ne plus contenir de paramètre `resize`, restaurant son comportement natif de redimensionnement en plein écran.
            *   **`style.css` :** La propriété `overflow: hidden` a été ajoutée au conteneur de l'iframe pour empêcher l'apparition de barres de défilement.
    *   **État à la fin de la session :** Le système est stable et la fonctionnalité VNC est entièrement opérationnelle et robuste.

### 6.4. Plan d'Action pour la Prochaine Session

*   **Priorité 1 : Implémenter la fonctionnalité de mise à jour des instances.**
    *   **Action 1 (Backend) :** Créer un nouvel endpoint d'API `PUT /api/instances/{instance_id}` pour gérer la mise à jour des données d'une instance (nom, GPU, autostart, etc.).
    *   **Action 2 (Backend) :** Implémenter la logique correspondante dans `database/crud.py`.
    *   **Action 3 (Frontend) :** Activer le bouton "Update" dans `static/app.js` et ajouter la logique pour envoyer les données modifiées de la ligne vers le nouvel endpoint.


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
        *   **Mode Normal :** L'accès se fait via une URL absolue construite à partir du `hostname` de l'instance (si défini) ou de l'hôte AiKore et du port de l'instance. NGINX route les requêtes vers le port interne de l'application.
        *   **Mode Persistant (KasmVNC) :** L'instance est directement exposée sur un port dédié du conteneur, défini par `AIKORE_INSTANCE_PORT_RANGE`.
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
    *   **Interface Persistante :** KasmVNC (Xvnc, Openbox)
    
    ---
    
    ## 4. Modèle de Données (Table `instances`, Schéma v2)
    
    | Nom de la Colonne     | Type de Données | Description                                                                 |
    |----------------------|-----------------|-----------------------------------------------------------------------------|
    | `id`                 | INTEGER         | Clé primaire.                                                               |
    | `name`               | STRING          | Nom unique défini par l'utilisateur pour l'instance.                         |
    | `base_blueprint`     | STRING          | Nom du fichier script de base (ex: "ComfyUI.sh").                           |
    | `gpu_ids`            | STRING          | Chaîne de caractères des ID de GPU (ex: "0,1"), passée à `CUDA_VISIBLE_DEVICES`. |
    | `autostart`          | BOOLEAN         | Si `true`, l'instance est lancée au démarrage d'AiKore.                     |
    | `persistent_mode`    | BOOLEAN         | Si `true`, l'instance est lancée dans une session de bureau KasmVNC.        |
    | `hostname`           | STRING          | **Nouveau :** Hostname/URL personnalisé pour l'accès direct à l'instance.      |
    | `status`             | STRING          | État actuel : 'stopped', 'starting', 'stalled', 'started', 'error'.         |
    | `pid`                | INTEGER         | Process ID du processus principal de l'instance.                            |
    | `port`               | INTEGER         | Port interne de l'application (toujours utilisé, souvent éphémère).         |
    | `persistent_port`    | INTEGER         | Port exposé à l'utilisateur pour l'interface KasmVNC. Utilisé si `persistent_mode` est vrai. |
    | `persistent_display` | INTEGER         | Numéro de l'affichage X11 virtuel utilisé par la session KasmVNC.           |
    
    ---
    
    ## 5. Arborescence du Projet (inchangée)
    
    ```
    📁 aikore/
        ...
    ```
    
    ---
    
    ## 6. État Actuel et Plan d'Action
    
    ### 6.1. Fonctionnalités Implémentées (Snapshot)
    
    Le projet a atteint une maturité fonctionnelle significative. Les fonctionnalités clés incluent :
    *   **Gestion CRUD+U d'Instances :** Création, lecture, **mise à jour** et suppression d'instances.
    *   **Système de Migration de Base de Données :** Un mécanisme de migration automatique et sécurisé met à jour le schéma de la base de données au démarrage de l'application, évitant les erreurs de désynchronisation.
    *   **Configuration Avancée des Instances :**
        *   **Hostname Personnalisé :** Permet de définir une URL d'accès spécifique pour chaque instance.
        *   **Sélection de GPU par Checkbox :** Interface utilisateur améliorée pour l'assignation des GPUs.
        *   **Sélection de Port à la Création :** Restauration de la possibilité de choisir un port lors de la création d'une instance.
    *   **Lancement de Processus :** Démarrage et arrêt des instances.
    *   **Interface Web Réactive :** Tableau de bord multi-panneaux avec état et statistiques en temps réel.
    *   **Correction des URLs d'Accès :** La génération des URLs pour les boutons "View" et "Open" est maintenant robuste et correcte pour tous les modes (persistant, non-persistant, avec ou sans hostname).
    *   **Intégration de KasmVNC :** Les instances persistantes lancent un serveur KasmVNC autonome et isolé.
    *   **Outils Avancés :** Visionneuse de Logs, Éditeur de Script, Terminal Intégré, Vue Embarquée.
    
    ### 6.2. Problèmes Connus et Points en Attente
    
    *   **Bugs d'Affichage Mineurs :** Des bugs mineurs subsistent dans l'affichage et la mise à jour dynamique du tableau des instances.
    
    ### 6.3. Journal d'Investigation
    
    *   **Session du 2025-11-06 (Partie 2) :**
        *   **Objectif :** Implémenter la fonctionnalité de mise à jour et corriger plusieurs régressions et demandes UX.
        *   **Défi Majeur :** L'ajout d'une simple colonne `hostname` à la base de données a révélé l'absence d'un système de migration, déclenchant une série de problèmes complexes qui sont devenus la priorité de la session.
        *   **Problèmes Résolus :**
            1.  **Mise en Place d'un Système de Migration de Base de Données :**
                *   Un script robuste a été intégré dans `main.py` pour versionner la DB.
                *   Il gère la sauvegarde, la création d'un nouveau schéma, le transfert des données et la vérification de l'intégrité.
                *   Plusieurs problèmes critiques ont été résolus pour le fiabiliser : `ImportError`, `readonly database` (dû à un `engine` SQLAlchemy périmé), et une condition de course ("zombie engine") résolue en forçant un redémarrage propre du conteneur après migration.
            2.  **Implémentation Backend Complète :** L'API a été enrichie avec les endpoints `PUT /api/instances/{id}` et `GET /api/system/info` (pour le nombre de GPUs).
            3.  **Refonte de l'Interface de Gestion :** Le frontend (`app.js`) a été mis à jour pour inclure le champ `hostname`, les checkboxes GPU, et le champ de port à la création.
            4.  **Fonctionnalité de Mise à Jour Complète :** Le bouton "Update" est maintenant pleinement fonctionnel.
            5.  **Correction de Bugs Frontend :** Le bug qui faisait disparaître le formulaire de création lors du rafraîchissement automatique du tableau a été corrigé en rendant la fonction de mise à jour moins destructive.
        *   **État à la fin de la session :** Le système est stable. Toutes les fonctionnalités prévues ont été implémentées et les régressions majeures sont corrigées. La base de données est maintenant versionnée et prête pour de futures évolutions.
    
    ### 6.4. Plan d'Action pour la Prochaine Session
    
    *   **Priorité 1 :** Analyser et corriger les bugs d'affichage mineurs restants dans le tableau des instances pour peaufiner l'expérience utilisateur.