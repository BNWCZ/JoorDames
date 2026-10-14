# Intégration Google Calendar

Ce guide explique comment connecter JoorDames à votre Google Calendar pour qu'il détecte automatiquement vos jours de télétravail et vos congés.

---

## 1. Introduction

Sans intégration Google Calendar, JoorDames réserve un bureau tous les jours ouvrés, sauf les jours fériés (toujours détectés). Avec l'intégration activée, le mode `sync` consulte votre agenda et marque dans `bookings.csv` les jours où vous n'êtes pas au bureau :

- Jours de **télétravail** (`out of office - remote`) : le bureau ne sera pas réservé.
- Jours de **congé ou vacances** (`out of office - holidays`) : le bureau ne sera pas réservé.
- Jours **fériés** (`out of office - public holiday`) : détectés automatiquement via le calendrier des jours fériés français, sans configuration supplémentaire.

La détection repose sur une correspondance insensible à la casse entre le titre des événements de votre agenda et les patterns que vous configurez dans `.env`.

---

## 2. Créer un projet Google Cloud

1. Rendez-vous sur [console.cloud.google.com](https://console.cloud.google.com).
2. Cliquez sur le sélecteur de projet en haut à gauche, puis sur **Nouveau projet**.
3. Donnez un nom au projet (par exemple `JoorDames`) et cliquez sur **Créer**.
4. Une fois le projet créé, assurez-vous qu'il est bien sélectionné dans le sélecteur.
5. Dans le menu de gauche, allez dans **API et services > Bibliothèque**.
6. Recherchez **Google Calendar API** et cliquez dessus.
7. Cliquez sur **Activer**.

---

## 3. Créer un compte de service

1. Dans le menu de gauche, allez dans **IAM et administration > Comptes de service**.
2. Cliquez sur **Créer un compte de service**.
3. Donnez-lui un nom (par exemple `joordames-reader`) et cliquez sur **Créer et continuer**.
4. L'attribution d'un rôle n'est pas nécessaire pour cette intégration. Cliquez sur **Continuer** puis sur **OK**.
5. Cliquez sur le compte de service nouvellement créé pour l'ouvrir.
6. Allez dans l'onglet **Clés**, cliquez sur **Ajouter une clé > Créer une clé**.
7. Sélectionnez le format **JSON** et cliquez sur **Créer**.
8. Un fichier JSON est téléchargé automatiquement. Renommez-le `service_account.json` et placez-le à la racine du projet JoorDames (avec Docker, il est monté dans le conteneur en lecture seule).

> Ne commitez jamais `service_account.json`. Il est déjà listé dans `.gitignore`.

---

## 4. Partager votre agenda avec le compte de service

1. Ouvrez [Google Calendar](https://calendar.google.com) dans votre navigateur.
2. Dans la colonne de gauche, survolez votre agenda principal et cliquez sur les trois points > **Paramètres et partage**.
3. Faites défiler jusqu'à la section **Partager avec des personnes spécifiques**.
4. Cliquez sur **+ Ajouter des personnes** et saisissez l'adresse e-mail du compte de service (elle est visible dans le fichier `service_account.json` sous la clé `client_email`, et ressemble à `joordames-reader@votre-projet.iam.gserviceaccount.com`).
5. Choisissez le niveau d'autorisation **Voir tous les détails des événements** et cliquez sur **Envoyer**.
6. Toujours dans les paramètres de l'agenda, faites défiler jusqu'à **Intégrer l'agenda** et copiez l'**Identifiant de l'agenda**. Il ressemble à votre adresse Gmail ou à une chaîne de caractères terminée par `@group.calendar.google.com`.

---

## 5. Configurer `.env`

Ajoutez les variables suivantes dans votre fichier `.env` :

```env
GOOGLE_CALENDAR_ID=votre.email@gmail.com
GOOGLE_SERVICE_ACCOUNT_PATH=service_account.json
REMOTE_WORKING_PATTERNS=Remote,Télétravail
OUT_OF_OFFICE_PATTERNS=Congé,Vacances
```

**`GOOGLE_CALENDAR_ID`** — L'identifiant de l'agenda copié à l'étape précédente. Pour votre agenda principal, c'est souvent votre adresse Gmail.

**`GOOGLE_SERVICE_ACCOUNT_PATH`** — Chemin vers le fichier JSON du compte de service. Si vous l'avez placé à la racine du projet, laissez `service_account.json`.

**`REMOTE_WORKING_PATTERNS`** — Liste de mots-clés séparés par des virgules. Tout événement dont le titre contient l'un de ces mots (insensible à la casse) sera traité comme un jour de télétravail. Exemples : un événement intitulé `Télétravail` ou `Remote working` sera détecté si vous avez `Remote,Télétravail`.

**`OUT_OF_OFFICE_PATTERNS`** — Liste de mots-clés pour les congés et absences. Tout événement correspondant sera traité comme un jour d'absence. Exemples : `Congé annuel`, `Vacances été` seront tous deux détectés si vous avez `Congé,Vacances`.

> Les patterns sont des sous-chaînes insensibles à la casse. `Congé` détectera `Congé annuel`, `RTT/Congé`, etc.
> Les jours fériés français sont détectés automatiquement et ne nécessitent pas de configuration.

---

## 6. Tester

Lancez une synchronisation manuelle :

```bash
python src/main.py sync
```

Le script consulte votre agenda sur les 90 prochains jours et met à jour `bookings.csv`. Vérifiez le fichier pour confirmer que vos jours de télétravail et congés ont bien été détectés :

```bash
cat bookings.csv
```

Les lignes correspondantes auront pour statut `out of office - remote` ou `out of office - holidays`.

Si aucune modification n'est détectée, le log affiche `no changes detected over the next 90 days`. La ligne `calendar: N out-of-office day(s) matched` indique combien de jours vos patterns ont reconnus : si elle affiche 0 alors que vous avez des événements, vérifiez `REMOTE_WORKING_PATTERNS` et `OUT_OF_OFFICE_PATTERNS`.

> Si vous obtenez une erreur d'authentification, vérifiez que le compte de service a bien accès à l'agenda (étape 4) et que `GOOGLE_SERVICE_ACCOUNT_PATH` pointe vers le bon fichier.
