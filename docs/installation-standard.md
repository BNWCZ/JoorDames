# Installation standard (sans Docker)

Ce guide explique comment installer et configurer JoorDames directement sur votre machine, sans Docker.

---

## 1. Prérequis

- Python 3.10 ou supérieur
- `pip` (inclus avec Python)
- `git`
- Une machine Linux ou macOS avec support cron (`crontab`)

> Windows n'est pas supporté. Si vous êtes sur Windows, utilisez WSL2 ou le guide d'installation Docker.

Vérifiez votre version de Python :

```bash
python3 --version
```

---

## 2. Cloner le dépôt

```bash
git clone https://github.com/BNWCZ/JoorDames.git
cd JoorDames
```

---

## 3. Installer les dépendances

Créez un environnement virtuel (recommandé) et installez les bibliothèques Python :

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Installez le navigateur Chromium utilisé par Playwright, avec ses dépendances système (Linux) :

```bash
playwright install --with-deps chromium
```

> Avec un environnement virtuel, les tâches cron doivent utiliser son Python : remplacez `python` par `/home/USER/JoorDames/venv/bin/python` dans la crontab (section 7).

---

## 4. Configurer l'environnement

Copiez le fichier d'exemple :

```bash
cp .env.example .env
```

Ouvrez `.env` et renseignez au minimum les variables suivantes :

```env
BOOKING_AREA=
BOOKING_DESK=
DOORJAMES_USERNAME=
DOORJAMES_PASSWORD=
```

**`BOOKING_AREA`** — La zone du bureau, telle qu'affichée dans le sélecteur de zone de la carte Door James (par exemple un étage).

**`BOOKING_DESK`** — Le nom exact du bureau, tel qu'affiché dans les résultats de recherche de la carte. Le plus simple pour trouver ces deux valeurs : faire une réservation manuelle et relever les noms affichés.

**`DOORJAMES_USERNAME`** / **`DOORJAMES_PASSWORD`** — Votre identifiant Door James (e-mail professionnel) et votre mot de passe Microsoft. Ils servent à ouvrir et renouveler la session automatiquement. Si votre e-mail Microsoft diffère de l'identifiant Door James, renseignez aussi `MICROSOFT_EMAIL`.

**`BOOKING_START`** / **`BOOKING_END`** *(facultatif)* — Le créneau réservé, au format `HH:MM` par pas de 15 minutes. Par défaut `09:00` et `17:00`.

Les autres variables (`APP_URL`, `SESSION_STATE_PATH`, `BOOKINGS_PATH`, `LOG_LEVEL`) ont des valeurs par défaut correctes ; ne les modifiez que si vous savez pourquoi.

> `.env` contient votre mot de passe : il est exclu de Git, ne le partagez jamais.

> Pour activer l'intégration Google Calendar, consultez [setup-google-calendar.md](setup-google-calendar.md).
> Pour activer les notifications et la commande skip Discord, consultez [setup-discord.md](setup-discord.md).

---

## 5. Première connexion

Il n'y a rien à faire de spécial : au premier lancement (par exemple le test `book` ci-dessous), aucune session n'existe encore, et JoorDames se connecte tout seul, sans fenêtre visible, via Microsoft SSO avec les identifiants du `.env`. La session est ensuite enregistrée dans `session/state.json` et rafraîchie à chaque exécution.

Quand la session expire, la même reconnexion automatique a lieu, et une notification Discord vous en informe.

> **Si Microsoft demande une validation MFA**, JoorDames vous envoie le code par Discord et attend deux minutes que vous approuviez sur votre téléphone.

**Connexion manuelle (dernier recours).** Si la reconnexion automatique échoue, ouvrez une session à la main, sur une machine avec écran :

1. Lancez `python src/main.py auth`. Une fenêtre de navigateur s'ouvre sur Door James.
2. Connectez-vous normalement (et approuvez la MFA si elle est demandée).
3. Une fois sur la page d'accueil de Door James, revenez dans le terminal et appuyez sur **Entrée**.

La session est sauvegardée dans `session/state.json`.

---

## 6. Tester manuellement chaque mode

Une fois l'authentification faite, testez chaque mode pour vérifier que tout fonctionne.

**Synchronisation avec Google Calendar :**

```bash
python src/main.py sync
```

Lit votre agenda sur les 90 prochains jours et met à jour `bookings.csv` avec les jours de télétravail, de congé ou de jours fériés détectés.

**Réservation de bureau :**

```bash
python src/main.py book
```

Réserve le bureau `BOOKING_DESK` pour le jour situé 41 jours dans le futur (créneau `BOOKING_START`–`BOOKING_END`, 09:00–17:00 par défaut), sauf si ce jour est un week-end, est déjà réservé ou est marqué hors du bureau dans `bookings.csv`.

**Check-in :**

```bash
python src/main.py checkin
```

Effectue le check-in pour la réservation d'aujourd'hui. Si aujourd'hui est marqué hors du bureau dans `bookings.csv`, annule la réservation du jour à la place. Le check-in n'ouvre que 30 minutes avant le début du créneau (8h30 pour un créneau à 9h00).

**Annulation :**

```bash
python src/main.py cancel
```

Annule la réservation d'aujourd'hui si elle existe.

**Rappel :**

```bash
python src/main.py reminder
```

Envoie une notification Discord si des événements de télétravail ne sont pas renseignés pour la semaine suivante.

---

## 7. Configurer les tâches cron

Ouvrez l'éditeur de crontab :

```bash
crontab -e
```

Ajoutez les lignes suivantes en remplaçant `/home/USER/JoorDames` par le chemin absolu de votre installation :

```
0 6 * * *     cd /home/USER/JoorDames && python src/main.py sync >> cron.log 2>&1
0 8 * * *     cd /home/USER/JoorDames && python src/main.py book >> cron.log 2>&1
45 8 * * 1-5  cd /home/USER/JoorDames && python src/main.py checkin >> cron.log 2>&1
0 14 * * 6    cd /home/USER/JoorDames && python src/main.py reminder >> cron.log 2>&1
0 20 * * 0    cd /home/USER/JoorDames && python src/main.py reminder >> cron.log 2>&1
```

**Explication des tâches :**

| Heure | Mode | Description |
|---|---|---|
| 6h00 tous les jours | `sync` | Synchronise Google Calendar et met à jour `bookings.csv` |
| 8h00 tous les jours | `book` | Réserve le bureau pour J+41 |
| 8h45 du lundi au vendredi | `checkin` | Check-in ou annulation selon le statut du jour |
| 14h00 le samedi | `reminder` | Rappel si la semaine suivante n'est pas renseignée |
| 20h00 le dimanche | `reminder` | Rappel de dernière minute pour le lundi |

> L'ordre des tâches est important : `sync` doit toujours s'exécuter avant `book`, et `book` avant `checkin`.

> Les chemins dans les tâches cron doivent être absolus. L'utilisation de `~` peut ne pas fonctionner selon la configuration cron de votre système.

Sauvegardez et quittez l'éditeur. Vérifiez que les tâches sont bien enregistrées :

```bash
crontab -l
```

---

## 8. Vérification finale

Chaque exécution écrit son journal applicatif dans `logs/joordames.log` ; en cas d'échec, une capture d'écran et le HTML de la page sont enregistrés dans `debug_out/`. La sortie brute des tâches cron va dans `cron.log` à la racine du projet.

Pour suivre les logs en temps réel :

```bash
tail -f /home/USER/JoorDames/logs/joordames.log
```

Pour consulter les dernières lignes :

```bash
tail -50 /home/USER/JoorDames/cron.log
```

> Si une tâche cron ne produit aucun log, vérifiez que le service cron est bien actif sur votre machine (`systemctl status cron` ou `systemctl status crond`).
