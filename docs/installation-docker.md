# Installation avec Docker

Ce guide explique comment installer et configurer JoorDames en utilisant Docker et Docker Compose.

---

## 1. Prérequis

- Docker (version 20.10 ou supérieure)
- Docker Compose (version 2.x ou supérieure — commande `docker compose`)
- `git`

Vérifiez que Docker est disponible :

```bash
docker --version
docker compose version
```

---

## 2. Cloner le dépôt

```bash
git clone https://github.com/BNWCZ/JoorDames.git
cd JoorDames
```

---

## 3. Configurer l'environnement

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

## 4. Construire l'image

Créez d'abord les fichiers et dossiers montés dans le conteneur (sinon Docker crée des dossiers vides à la place des fichiers) :

```bash
mkdir -p session logs debug debug_out
touch bookings.csv
```

> Si vous n'utilisez pas Google Calendar, ne créez pas `service_account.json` : JoorDames détecte son absence et ignore simplement l'agenda.

Puis construisez l'image :

```bash
docker compose build
```

Cette commande télécharge l'image de base (`mcr.microsoft.com/playwright/python:v1.49.1-jammy`) et installe les dépendances du projet. L'opération peut prendre quelques minutes lors du premier build.

---

## 5. Première connexion

Il n'y a rien à faire de spécial : au premier lancement (par exemple le test `book` ci-dessous), aucune session n'existe encore, et JoorDames se connecte tout seul, sans fenêtre visible, via Microsoft SSO avec les identifiants du `.env`. La session est ensuite enregistrée dans `session/state.json` (monté dans le conteneur) et rafraîchie à chaque exécution.

Quand la session expire, la même reconnexion automatique a lieu, et une notification Discord vous en informe.

> **Si Microsoft demande une validation MFA**, JoorDames vous envoie le code par Discord et attend deux minutes que vous approuviez sur votre téléphone.
>
> **En dernier recours**, connectez-vous à la main dans un navigateur visible. Cela ne fonctionne pas dans Docker : il faut Python sur une machine avec écran (voir le [guide d'installation standard](installation-standard.md), sections 3 à 5), puis copier le `session/state.json` obtenu dans le dossier `session/` de votre installation Docker.

---

## 6. Tester manuellement chaque mode

**Synchronisation avec Google Calendar :**

```bash
docker compose run --rm joordames python src/main.py sync
```

Lit votre agenda sur les 90 prochains jours et met à jour `bookings.csv` avec les jours de télétravail, de congé ou de jours fériés détectés.

**Réservation de bureau :**

```bash
docker compose run --rm joordames python src/main.py book
```

Réserve le bureau `BOOKING_DESK` pour le jour situé 41 jours dans le futur (créneau `BOOKING_START`–`BOOKING_END`, 09:00–17:00 par défaut), sauf si ce jour est un week-end, est déjà réservé ou est marqué hors du bureau dans `bookings.csv`.

**Check-in :**

```bash
docker compose run --rm joordames python src/main.py checkin
```

Effectue le check-in pour la réservation d'aujourd'hui. Si aujourd'hui est marqué hors du bureau dans `bookings.csv`, annule la réservation du jour à la place.

**Annulation :**

```bash
docker compose run --rm joordames python src/main.py cancel
```

Annule la réservation d'aujourd'hui si elle existe.

**Rappel :**

```bash
docker compose run --rm joordames python src/main.py reminder
```

Envoie une notification Discord si des événements de télétravail ne sont pas renseignés pour la semaine suivante.

---

## 7. Configurer les tâches cron

Ouvrez l'éditeur de crontab sur la machine hôte :

```bash
crontab -e
```

Ajoutez les lignes suivantes en remplaçant `/home/USER/JoorDames` par le chemin absolu de votre installation :

```
0 6 * * *     cd /home/USER/JoorDames && docker compose run --rm joordames python src/main.py sync >> cron.log 2>&1
0 8 * * *     cd /home/USER/JoorDames && docker compose run --rm joordames python src/main.py book >> cron.log 2>&1
45 8 * * 1-5  cd /home/USER/JoorDames && docker compose run --rm joordames python src/main.py checkin >> cron.log 2>&1
0 14 * * 6    cd /home/USER/JoorDames && docker compose run --rm joordames python src/main.py reminder >> cron.log 2>&1
0 20 * * 0    cd /home/USER/JoorDames && docker compose run --rm joordames python src/main.py reminder >> cron.log 2>&1
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

> Chaque exécution de `docker compose run --rm` démarre un conteneur temporaire qui s'arrête automatiquement une fois la commande terminée.

Sauvegardez et quittez l'éditeur. Vérifiez que les tâches sont bien enregistrées :

```bash
crontab -l
```

---

## 8. Vérification

Chaque exécution écrit son journal applicatif dans `logs/joordames.log` ; en cas d'échec, une capture d'écran et le HTML de la page sont enregistrés dans `debug_out/`. La sortie brute de Docker (démarrage du conteneur, erreurs d'image) va dans `cron.log` à la racine du projet.

Pour suivre les logs en temps réel :

```bash
tail -f /home/USER/JoorDames/logs/joordames.log
```

Pour consulter les dernières lignes :

```bash
tail -50 /home/USER/JoorDames/cron.log
```

> Si une tâche cron ne produit aucun log, vérifiez que le service cron est bien actif sur votre machine (`systemctl status cron` ou `systemctl status crond`) et que la commande `docker compose` est accessible dans le PATH utilisé par cron.
