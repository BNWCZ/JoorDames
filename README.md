# JoorDames

Automatisation des réservations de bureau sur [Door James](https://spa.doorjames.app).

JoorDames réserve automatiquement **votre bureau habituel 41 jours à l'avance**, fait le check-in chaque matin, et annule la réservation les jours où vous n'êtes pas au bureau. Le tout piloté par votre agenda Google Calendar, avec une notification Discord à chaque action.

> [!WARNING]
> **Outil non officiel.** JoorDames est un projet personnel, sans lien avec Door James ni avec votre employeur, et n'est ni validé ni supporté par eux. Il pilote l'interface web de Door James comme le ferait un utilisateur, avec **vos propres identifiants**, qui restent uniquement sur votre machine (fichier `.env`, jamais commité).
>
> Avant de l'utiliser, vérifiez qu'il est compatible avec les règles d'usage informatique de votre entreprise. Vous l'utilisez à vos risques et périls.
>
> Jouez le jeu : renseignez vos absences dans votre agenda pour que les bureaux que vous n'utilisez pas soient libérés pour vos collègues.

---

## Comment ça marche

Chaque jour, JoorDames enchaîne trois étapes :

1. **Synchronisation** — lit votre Google Calendar sur 90 jours et marque dans `bookings.csv` vos jours de télétravail, de congé et les jours fériés.
2. **Réservation** — réserve le bureau `BOOKING_DESK` (zone `BOOKING_AREA`) pour le jour **J+41**, de `BOOKING_START` à `BOOKING_END` (09:00–17:00 par défaut). Les week-ends et jours marqués « hors du bureau » sont ignorés.
3. **Check-in** — le matin, fait le check-in sur la réservation du jour ; si le jour est marqué « hors du bureau », annule la réservation à la place.

Chaque réservation est vérifiée dans l'agenda Door James avant d'être déclarée réussie.

**Période de démarrage :** comme JoorDames réserve à J+41, les six premières semaines ne sont pas couvertes. Continuez à réserver à la main pendant ce temps.

**Site :** JoorDames utilise le site (bâtiment) par défaut de votre profil Door James. Vérifiez qu'il est correct avant de commencer.

### Le fichier `bookings.csv`

C'est la mémoire de JoorDames : une ligne par jour, avec son statut.

| Statut | Signification |
|---|---|
| `booked` | Bureau réservé, check-in à faire |
| `checked_in` | Check-in effectué |
| `cancelled` | Réservation annulée |
| `error` | La dernière action a échoué (voir les logs) |
| `out of office - remote` | Télétravail (Google Calendar) |
| `out of office - holidays` | Congés (Google Calendar) |
| `out of office - public holiday` | Jour férié (détecté automatiquement) |

> **Sans Google Calendar**, JoorDames ne sait pas quand vous êtes absent : il réserve et fait le check-in tous les jours ouvrés. Vous devrez annuler vous-même les jours de télétravail ou de congé. Les jours fériés restent détectés automatiquement.

---

## Prérequis

- **Une machine allumée aux heures des tâches planifiées** — un serveur, un NAS, un Raspberry Pi… Linux ou macOS (sous Windows : WSL2).
- **Docker + Docker Compose v2** *(recommandé)*, **ou** Python 3.10+.
- **Un compte Door James** (connexion via Microsoft SSO), avec son identifiant et son mot de passe.
- *(Optionnel)* **Un compte Google** et un projet Google Cloud gratuit, pour l'intégration agenda.
- *(Optionnel)* **Un serveur Discord** dont vous êtes administrateur, pour les notifications.

### Dépendances

Toutes sont installées automatiquement (image Docker ou `pip install -r requirements.txt`) :

| Paquet | Rôle |
|---|---|
| [`playwright`](https://playwright.dev/python/) + Chromium | Pilote le navigateur sur Door James |
| `google-api-python-client`, `google-auth` | Lecture de Google Calendar (compte de service) |
| `holidays` | Jours fériés français |
| `requests` | Notifications et commandes Discord |
| `python-dotenv`, `pytz` | Configuration et fuseau horaire Europe/Paris |

L'image Docker est basée sur `mcr.microsoft.com/playwright/python`, qui embarque déjà Chromium.

---

## Démarrage rapide (Docker)

```bash
git clone https://github.com/BNWCZ/JoorDames.git
cd JoorDames
cp .env.example .env               # puis remplissez-le (voir Configuration)
mkdir -p session logs debug debug_out && touch bookings.csv
docker compose build
docker compose run --rm joordames python src/main.py book
```

Le premier lancement n'a pas encore de session : JoorDames se connecte tout seul, en arrière-plan, avec les identifiants du `.env`, puis enregistre la session dans `session/state.json` pour les fois suivantes.

Il ne reste plus qu'à planifier les tâches (voir [Planning](#planning)).

Guides détaillés :
- [Installation Docker](docs/installation-docker.md)
- [Installation sans Docker](docs/installation-standard.md)
- [Configurer Google Calendar](docs/setup-google-calendar.md)
- [Configurer Discord](docs/setup-discord.md)

---

## Configuration

Tout se règle dans `.env` (copié depuis `.env.example`). Ce fichier contient votre mot de passe : il est exclu de Git, ne le partagez pas.

| Variable | Obligatoire | Description |
|---|---|---|
| `BOOKING_AREA` | oui | Zone du bureau, telle qu'affichée dans le sélecteur de zone de la carte (ex. un étage) |
| `BOOKING_DESK` | oui | Nom exact du bureau, tel qu'affiché dans les résultats de recherche de la carte |
| `BOOKING_START` / `BOOKING_END` | non | Créneau réservé, `HH:MM` par pas de 15 min (défaut `09:00` / `17:00`) |
| `DOORJAMES_USERNAME` | oui | Votre identifiant Door James (e-mail professionnel) |
| `DOORJAMES_PASSWORD` | oui | Votre mot de passe Microsoft, utilisé pour renouveler la session automatiquement |
| `MICROSOFT_EMAIL` | non | E-mail Microsoft, s'il diffère de `DOORJAMES_USERNAME` |
| `GOOGLE_CALENDAR_ID`, `GOOGLE_SERVICE_ACCOUNT_PATH`, `REMOTE_WORKING_PATTERNS`, `OUT_OF_OFFICE_PATTERNS` | non | Intégration agenda — voir [setup-google-calendar.md](docs/setup-google-calendar.md) |
| `DISCORD_WEBHOOK_URL`, `DISCORD_BOT_TOKEN`, `DISCORD_COMMAND_CHANNEL_ID` | non | Intégration Discord — voir [setup-discord.md](docs/setup-discord.md) |
| `LOG_LEVEL` | non | `INFO` (défaut) ou `DEBUG` pour le détail de chaque clic |
| `APP_URL`, `SESSION_STATE_PATH`, `BOOKINGS_PATH` | non | À ne modifier que si vous savez pourquoi |

Pour trouver `BOOKING_AREA` et `BOOKING_DESK`, faites une réservation manuelle et relevez le nom de la zone et du bureau tels qu'ils apparaissent sur la carte.

---

## Session et authentification

La session Door James est sauvegardée dans `session/state.json` et rafraîchie à chaque exécution. Quand elle expire malgré tout, JoorDames se reconnecte seul via Microsoft SSO avec les identifiants du `.env`, et vous prévient sur Discord.

Si Microsoft demande une validation MFA, JoorDames vous envoie le code par Discord et attend deux minutes que vous approuviez sur votre téléphone. En cas d'échec, connectez-vous à la main, avec une fenêtre de navigateur visible (hors Docker, voir [installation sans Docker](docs/installation-standard.md)) :

```bash
python src/main.py auth
```

---

## Planning

Horaires par défaut, à placer dans la crontab de la machine hôte. Les commandes exactes sont dans les guides d'installation.

| Heure | Jours | Commande | Action |
|---|---|---|---|
| 6h00 | tous | `sync` | Synchronise Google Calendar → `bookings.csv` |
| 8h00 | tous | `book` | Réserve le bureau à J+41 |
| 8h45 | lun–ven | `checkin` | Check-in, ou annulation si absent |
| 14h00 | samedi | `reminder` | Alerte si aucun télétravail n'est saisi pour la semaine suivante |
| 20h00 | dimanche | `reminder` | Idem, dernier rappel |

L'ordre compte : `sync` avant `book`, `book` avant `checkin`. Le check-in Door James n'ouvre que 30 minutes avant le début du créneau : si vous changez `BOOKING_START`, décalez le `checkin` en conséquence.

### Commandes disponibles

```bash
python src/main.py sync      # Synchroniser Google Calendar
python src/main.py book      # Réserver le bureau à J+41
python src/main.py checkin   # Check-in du jour (ou annulation si absent)
python src/main.py cancel    # Annuler la réservation du jour
python src/main.py reminder  # Rappel télétravail de la semaine suivante
python src/main.py auth      # Connexion manuelle (navigateur visible, hors Docker)
```

Avec Docker, préfixez par `docker compose run --rm joordames`.

---

## Discord

- **Notifications** (webhook) : réservation, check-in, annulation, renouvellement de session, erreurs. Elles sont silencieuses les week-ends, jours fériés et jours de congé, sauf les erreurs.
- **Commande `skip`** (bot) : envoyez `skip` dans le canal de commande avant 8h45 pour sauter l'action du jour (check-in ou annulation).

Voir [setup-discord.md](docs/setup-discord.md).

---

## Logs et dépannage

Chaque exécution écrit dans `logs/joordames.log` (rotation à 5 Mo, 5 archives) :

```
2026-09-10 10:00:49 INFO  [cancel] ─── run start (mode=cancel, pid=1) ───
2026-09-10 10:00:56 INFO  [cancel] session valid (url=https://spa.doorjames.app/)
2026-09-10 10:01:14 ERROR [cancel] cancellation failed for 2026-09-10: No booking found to cancel
```

```bash
tail -f logs/joordames.log           # suivre en direct
grep ERROR logs/joordames.log        # uniquement les erreurs
```

En cas d'échec, une capture d'écran et le HTML de la page sont enregistrés dans `debug_out/` (le chemin figure dans le log). `LOG_LEVEL=DEBUG` détaille chaque clic et chaque attente.

---

## Quand Door James change son interface

JoorDames clique dans l'interface web comme un humain : **chaque refonte de Door James peut le casser**, ce qui est arrivé plusieurs fois en 2026. Le symptôme typique est une erreur `Timeout … waiting for locator` sur Discord.

Pour réparer :

1. Ouvrez la capture et le HTML dans `debug_out/` pour voir où le parcours s'est arrêté.
2. Corrigez le sélecteur concerné dans `src/spa_booker.py` (réservation, check-in, annulation) ou `src/auth.py` (connexion).
3. Reconstruisez l'image (`docker compose build`) : le code est copié dans l'image, pas monté.

[`CLAUDE.md`](CLAUDE.md) recense toutes les pannes rencontrées et leur correction. Il sert de contexte à [Claude Code](https://claude.com/claude-code), qui sait très bien mener ce genre de diagnostic, mais il se lit aussi très bien sans.

---

## Licence

[MIT](LICENSE) — © 2026 BCZ
