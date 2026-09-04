# BUG live — instances persistent-mode FreeToken Desktop (native, no web UI) tuées après démarrage

Statut : **investigation LECTURE SEULE** terminée + **test mocké** reproduisant/validant.
Fichier `aikore/core/process_manager.py` — **non modifié** (WIP utilisateur). Correctif proposé (patch process_manager) NON appliqué, donné à valider.

---

## 1. Mécanisme exact tracé (fonctions : lignes)

### La sonde du monitor (QUEL port ?)
`start_instance_process` (process_manager.py:741-745), branche persistent :
```python
port_to_monitor = instance.persistent_port
internal_app_port = instance.persistent_port
```
`monitor_instance_thread` (process_manager.py:441) sonde exclusivement
`internal_app_port` — process_manager.py:468 :
```python
response = requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)
```
⇒ **En mode persistent, le monitor sonde le **port VNC/KasmVNC** (`persistent_port`, servi par Xvnc) — PAS le moteur 1919.** Xvnc répond `<500` dès que le desktop est prêt.

### Ce qui se passe quand la sonde réussit (le BUG)
process_manager.py:470-511 :
```python
if response.status_code < 500:
    print("Instance is RUNNING ...")
    with SessionLocal() as db:            # promotion starting->started (M2)
        ...
    if persistent_display is not None:
        ...
        ff_process = subprocess.Popen(['/usr/bin/firefox', ...])  # lance le kiosque
        firefox_processes[instance_id] = ff_process
    break                                 # <=== LIGNE 511 : sortie immédiate de la boucle
```
Juste APRÈS la boucle, le bloc « teardown » est exécuté **inconditionnellement** (process_manager.py:545-566) :
- `popen.wait(timeout=5)` (552),
- `running_instances.pop(instance_id, None)` (557) → **retire l’entrée de tracking**,
- `terminate_firefox_for_instance(instance_id)` (565) → **tue le Firefox qu’il vient de lancer**.

Ce bloc était conçu pour ne tourner QUE sur la **mort réelle du process** (déclenchée par les `break` de 463/465). Mais le `break` de la branche succès (511) y tombe aussi ⇒ **le monitor se désenregistre et tue le kiosque immédiatement après le premier poll réussi**, alors que le process principal (kasm_launcher.sh, PID X) est TOUJOURS VIVANT. Aucun timeout 180s ne gère ça — le bug est ce `break`, pas un timeout.

### Firefox tracking LOT-3 (`terminate_firefox_for_instance`)
- Déf. : process_manager.py:206, killpg SESSION du Firefox uniquement (start_new_session=True, ligne ~505-510).
- Appels : (1) dans le teardown du monitor — 565 ; (2) dans `finally` de `stop_instance_process` — 827.
- **Dans le bug, c’est le chemin (1)** : le monitor tue le kiosque juste après l’avoir lancé.

### Cycle complet (instances.py / stop)
`stop_instance_process` (process_manager.py:784) : le `killpg(SIGTERM)` du groupe N’est exécuté que si `instance_id in running_instances` (794-797) ; sinon il affiche « Stop requested, but instance 1 not in running_instances » (795) et ne tue **personne**.

---

## 2. Cause racine du exit 143 (GUI freetoken-desktop)

**Qui envoie le SIGTERM au GUI :** seuls 2 émetteurs existent dans le code (grep confirmé) :
- `terminate_firefox_for_instance` — ne cible QUE le groupe Firefox (pas le GUI),
- `stop_instance_process` — `killpg` du groupe principal, **mais conditionné à la présence de l’entrée**.

La séquence observée s’explique ainsi :
1. Monitor : poll VNC OK → lance Firefox → `break` (511) → teardown → **pop de l’entrée** (557) + **kill du Firefox** (565). ⇒ « Firefox (PID X+18) terminated for instance 1 ».
2. Le groupe FreeToken (Xvnc/openbox/blueprint/GUI) continue de tourner mais devient **ORPHELIN/INTENDU** (plus de monitor, plus d’entrée).
3. Quand un `SIGTERM` atteint le superviseur blueprint.sh (qu’il provienne d’une action destructive ultérieure ayant capturé ce groupe, d’un TERM niveau KasmVNC/session, ou de l’environnement), le trap `cleanup()` (FreeToken.sh) exécute `kill ${GUI_PID}` → **GUI exit 143** → trap EXIT → « teardown blueprint ».
4. Au clic Stop suivant : entrée déjà absente ⇒ « Stop requested, but instance 1 not in running_instances » (795) − et comme l’entrée manque, **AiKore ne peut plus proprement tuer le groupe**.

- **H1 (sonde 1919 DOWN)** : FAUX — le monitor sonde le port VNC, qui répond.
- **H2 (mort Firefox vue comme mort instance)** : FAUX — le monitor ne surveille jamais Firefox ; il tue Firefox par conséquent de son propre teardown prématuré.
- **H3 (le teardown lot-3 / terminate_firefox est appelé, déclenché par la sonde)** : **CONFIRMÉ** — mais au sens précis : c’est le `break` de la *sonde qui RÉUSSIT* (VNC), pas une sonde qui échoue.

**Pourquoi le 1er run a survécu :** timing/condition d’ordonnancement. Le bug ne se déclenche que lorsque le poll VNC renvoie `<500` alors que la session était encore suivie (fenêtre qui, au 1er launch — install du .deb, engine non encore installé, desktop en cours de premier boot — laisse un timing favorable). La cause n’est pas pinable uniquement par le code ; c’est une course, exactement comme décrit (« timing favorable »).

---

## 3. Correctif retenu

### (a) Blueprint-side ? — NON FAISABLE proprement
Le bug se déclenche au **1er poll réussi du port VNC**, que le blueprint DOIT servir pour que le desktop fonctionne. Une sonde keep-alive sur 1919 ne change rien : ce n’est pas le port sondé par la readiness (c’est le port VNC). Aucun serveur keep-alive blueprint ne peut empêcher le monitor de `break` puis de teardown. ⇒ On retient (b).

### (b) Patch `process_manager.py` (PROPOSÉ, NON appliqué)
Rendre le monitor « sticky » : une fois l’instance prête (appelée « ready »), le monitor **continue de boucler** au lieu de `break` ; il ne teardown **que si le process meurt réellement** (`popen.poll() != None`). Le kiosque Firefox survit et l’entrée `running_instances` reste présente pour le Stop.

Diff proposé (voir aussi `proposed_fix_monitor.patch`) :

```diff
     start_time = time.time()
     last_log_time = 0.0
+    # Fix: une fois prêt, on continue à boucler pour garder l'entrée + Firefox.
+    # On ne teardown QUE si le process meurt réellement (popen.poll() != None).
+    app_ready = False
     
     while True:
         if popen is not None:
             if popen.poll() is not None:
                 break
         elif not psutil.pid_exists(pid):
             break
         try:
-            # Poll the internal application port to confirm it's truly ready
-            response = requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)
-            
-            if response.status_code < 500:
-                print(f"[Monitor-{instance_id}] Instance is RUNNING on port {internal_app_port}.")
-                with SessionLocal() as db:
-                    updated_rows = (
-                        db.query(models.Instance)
-                        .filter(...status == "starting")
-                        .update({"status": "started"})
-                    )
-                    db.commit()
-                    if updated_rows == 0:
-                        print(f"[Monitor-{instance_id}] Status no longer 'starting'; skipping 'started' update.")
-
-                if persistent_display is not None:
-                    print(...)
-                    firefox_profile_dir = ...
-                    ff_env = ...
-                    ff_process = subprocess.Popen(['/usr/bin/firefox', ...], ...)
-                    firefox_processes[instance_id] = ff_process
-                break
+            if not app_ready:
+                response = requests.get(f"http://127.0.0.1:{internal_app_port}", timeout=2)
+                if response.status_code < 500:
+                    app_ready = True
+                    print(f"[Monitor-{instance_id}] Instance is RUNNING on port {internal_app_port}.")
+                    with SessionLocal() as db:
+                        updated_rows = (
+                            db.query(models.Instance)
+                            .filter(...status == "starting")
+                            .update({"status": "started"})
+                        )
+                        db.commit()
+                        if updated_rows == 0:
+                            print(...)
+                    if persistent_display is not None:
+                        print(...)
+                        firefox_profile_dir = ...
+                        ff_env = ...
+                        ff_process = subprocess.Popen(['/usr/bin/firefox', ...], ...)
+                        firefox_processes[instance_id] = ff_process
+                # PAS de break : garder l'entrée + Firefox vivants.
+                continue
+            time.sleep(MONITOR_POLL_INTERVAL)
         
         except requests.exceptions.ConnectionError:
-            ...
+            if not app_ready:
+                ...
             time.sleep(MONITOR_POLL_INTERVAL)
         
         except Exception as e:
-            print(f"[Monitor-{instance_id}] An unexpected error occurred: {e}")
+            if not app_ready:
+                print(f"[Monitor-{instance_id}] An unexpected error occurred: {e}")
             time.sleep(MONITOR_POLL_INTERVAL)
     
-    # Process died while still in "starting" status — mark as stalled
-    print(f"[Monitor-{instance_id}] Process with PID {pid} no longer exists.")
+    # Le process est réellement mort (ou n'est jamais devenu prêt)
+    print(f"[Monitor-{instance_id}] Process with PID {pid} no longer exists.")
     with SessionLocal() as db:
         ... (inchangé : stalled uniquement si encore "starting")
```

Propriétés du patch :
- **Ne touche pas** au killpg du groupe (inchangé), ni à `terminate_firefox_for_instance`.
- Préserve LOT3 M2 (poll zombie-safe) et M4 (tracking Firefox).
- Corrige AUSSI le mode normal (qui avait le même `break` prématuré).
- L’entrée reste dans `running_instances` tant que le process vit ⇒ le Stop retrouve l’instance et peut killpg proprement (plus de « Stop not in running_instances »).
- Le kiosque Firefox reste affiché pendant toute la session, puis est proprement terminé au Stop/mort réelle.

**Signal utilisable pour ne teardown que si pas de web UI :** le patch ci-dessus le règle de façon générique (le monitor ne teardown plus par succès de sonde, quel que soit le mode), donc pas besoin de câbler une metadata.

---

## 4. Validation (test mocké) — `tests/test_monitor_teardown_mock.py`

Exécution (harness auto-suffisant, fake `requests`/`psutil`/`sqlalchemy`/`aikore.*`) :
```
=== Reproducing the live bug (current process_manager WIP) ===
[Monitor-1] Instance is RUNNING on port 9001.
[Monitor-1] Persistent mode detected. Launching Firefox on display :9001.
[Monitor-1] Pointing internal Firefox to http://127.0.0.1:1919
[Monitor-1] Process with PID 1000 no longer exists.          <- teardown prématuré
[Monitor-1] Process died before becoming ready. Marked as STALLED.
[Monitor-1] Removed dead process entry from running_instances.  <- entrée retirée process vivant
[Manager] Firefox (PID 999999) terminated for instance 1.        <- kiosque tué
[mock] BUG REPRODUCED: entry dropped + Firefox killed while process alive

=== Validating the proposed fix (in-memory only) ===
[mock] FIX OK: while alive -> entry tracked + Firefox ALIVE
[mock] FIX OK: after death -> entry dropped + Firefox cleaned up

ALL MOCK TESTS PASSED.
```

- **Bug reproduit** : le monitor retire l'entrée + tue le Firefox alors que le process principal est vivant (exactement les logs live).
- **Fix validé** : tant que le process vit → entrée présente + Firefox vivant ; à la mort réelle → cleanup propre (entrée retirée + Firefox terminé).
- Aucune modification appliquée à `process_manager.py`.

---

## Fichiers
- `tests/test_monitor_teardown_mock.py` — harness mocké (réussite).
- `proposed_fix_monitor.patch` — diff proposé à valider par l'utilisateur (NON appliqué).
