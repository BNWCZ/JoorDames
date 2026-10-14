# Intégration Discord

Ce guide explique comment connecter JoorDames à Discord pour recevoir des notifications et utiliser la commande skip.

---

## 1. Introduction

JoorDames propose deux fonctionnalités Discord indépendantes :

- **Notifications (webhook)** : le script envoie un message dans un canal Discord à chaque événement significatif (réservation réussie, check-in, annulation, erreur, session expirée).
- **Commande skip (bot)** : en postant `skip` dans un canal dédié avant l'exécution de `python src/main.py checkin`, vous annulez l'action automatique du jour (check-in ou annulation de réservation).

Vous pouvez activer l'une sans l'autre. Si ni `DISCORD_WEBHOOK_URL` ni `DISCORD_BOT_TOKEN` ne sont renseignés, le script fonctionne normalement sans envoyer de notifications.

---

## Partie 1 : Notifications (webhook)

### 2. Créer un webhook

1. Ouvrez Discord et rendez-vous dans le canal où vous souhaitez recevoir les notifications.
2. Cliquez sur l'engrenage à côté du nom du canal pour ouvrir les **Paramètres du canal**.
3. Dans le menu de gauche, cliquez sur **Intégrations**.
4. Cliquez sur **Webhooks**, puis sur **Nouveau webhook**.
5. Donnez-lui un nom (par exemple `JoorDames`) et cliquez sur **Copier l'URL du webhook**.

### 3. Configurer `.env`

Ajoutez la variable suivante dans votre fichier `.env` :

```env
DISCORD_WEBHOOK_URL=
```

Collez l'URL copiée à l'étape précédente directement après le signe `=`. L'URL ressemble à `https://discord.com/api/webhooks/123456789/abcdef...`.

### 4. Notifications silencieuses

Certaines notifications sont envoyées en mode silencieux : le message apparaît dans le canal mais ne génère pas de son ni de notification push sur votre téléphone ou votre bureau. Ce comportement s'applique aux événements qui se produisent pendant des périodes où vous n'êtes pas au bureau selon votre calendrier, à savoir :

- Les week-ends.
- Les jours fériés français.
- Les jours marqués comme congé ou vacances dans votre agenda (`out of office - holidays`).

Les notifications de synchronisation de calendrier (`sync`) sont également toujours silencieuses.

Les notifications d'erreur et d'expiration de session sont toujours envoyées normalement (avec son et notification push).

### 5. Tester

Lancez n'importe quel mode du script :

```bash
python src/main.py sync
```

Si des modifications sont détectées, un message apparaît dans votre canal Discord. Vous pouvez également lancer `python src/main.py book` ou `python src/main.py checkin` pour déclencher une notification immédiate (attention : ces commandes agissent réellement sur Door James).

> Avec Docker, préfixez les commandes par `docker compose run --rm joordames`, par exemple `docker compose run --rm joordames python src/main.py sync`.

---

## Partie 2 : Commande skip (bot)

### 6. Introduction

La commande skip permet d'annuler l'action automatique prévue au moment de l'exécution de `python src/main.py checkin` pour la journée en cours. En postant le message `skip` dans le canal de commande avant cette exécution, le script détecte le message, le supprime, et saute l'action du jour :

- Si c'est un jour de bureau prévu : le check-in est ignoré.
- Si c'est un jour hors du bureau (télétravail ou congé) : l'annulation de réservation est ignorée.

Une confirmation est envoyée par notification si le webhook est configuré.

### 7. Créer le bot

1. Rendez-vous sur [discord.com/developers/applications](https://discord.com/developers/applications).
2. Cliquez sur **New Application**, donnez-lui un nom (par exemple `JoorDames`) et cliquez sur **Create**.
3. Dans le menu de gauche, cliquez sur **Bot**.
4. Sous le nom du bot, cliquez sur **Reset Token** et confirmez. Copiez le token affiché immédiatement — il ne sera plus visible ensuite.
5. Ouvrez votre fichier `.env` et collez le token sur la ligne `DISCORD_BOT_TOKEN=` (voir étape 11 ci-dessous).
6. Toujours sur la page Bot, faites défiler jusqu'à **Privileged Gateway Intents** et activez **Message Content Intent**. Cliquez sur **Save Changes**.

> Conservez le token du bot en lieu sûr. Il donne accès complet au bot.

### 8. Inviter le bot sur votre serveur

1. Dans le menu de gauche, allez dans **OAuth2 > URL Generator**.
2. Dans la section **Scopes**, cochez `bot`.
3. Dans la section **Bot Permissions** qui apparaît, cochez :
   - **Read Messages/View Channels**
   - **Manage Messages** (nécessaire pour supprimer les messages `skip`)
4. Copiez l'URL générée en bas de page, collez-la dans votre navigateur et invitez le bot sur votre serveur Discord.

### 9. Donner accès au canal de commande

Par défaut, le bot peut ne pas voir tous les canaux. Pour lui donner accès au canal dédié :

1. Faites un clic droit sur le canal de commande et cliquez sur **Modifier le canal**.
2. Allez dans **Permissions** et cliquez sur le `+` pour ajouter une permission.
3. Recherchez et sélectionnez votre bot.
4. Activez les permissions **Voir le canal** et **Gérer les messages**.
5. Cliquez sur **Enregistrer les modifications**.

### 10. Récupérer l'ID du canal

1. Dans Discord, ouvrez les **Paramètres utilisateur** (engrenage en bas à gauche).
2. Allez dans **Apparence** et activez le **Mode développeur**.
3. Fermez les paramètres, faites un clic droit sur le canal de commande et cliquez sur **Copier l'identifiant du canal**.

### 11. Configurer `.env`

Ajoutez les variables suivantes dans votre fichier `.env` :

```env
DISCORD_BOT_TOKEN=
DISCORD_COMMAND_CHANNEL_ID=
```

- `DISCORD_BOT_TOKEN` : collez le token copié à l'étape 7 directement après le `=`.
- `DISCORD_COMMAND_CHANNEL_ID` : collez l'identifiant du canal copié à l'étape 10 directement après le `=`.

### 12. Utilisation

Postez le message suivant dans le canal de commande **avant l'heure planifiée de `python src/main.py checkin`** dans votre crontab (8h45 dans la configuration recommandée) :

```
skip
```

Le script lit les 50 derniers messages du canal au moment de l'exécution de `checkin`, détecte le message `skip`, le supprime, et ignore l'action automatique du jour. Une notification de confirmation est envoyée si le webhook est configuré.

> Le message doit contenir exactement `skip` en minuscules. Tout autre contenu est ignoré.
> Si le bot n'est pas configuré (`DISCORD_BOT_TOKEN` absent), `python src/main.py checkin` s'exécute normalement sans vérifier les commandes.
