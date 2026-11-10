# Bot de suivi de tendance — BTC, ETH, or

## Ce que fait le bot
Une fois par jour, juste après 00:00 UTC, il regarde 3 marchés, tous tradés
automatiquement sur l'exchange : Bitcoin, Ethereum et l'or (via PAXG, un jeton
adossé à l'or). Chaque marché a un tiers du capital. Un 4e marché, le Nasdaq-100
à trader à la main, est disponible en option (`BOT_WITH_NASDAQ=1`).

Pour chaque marché, il calcule 7 moyennes mobiles (30, 40, 50, 60, 70, 80 et
100 jours). Si le prix est au-dessus de 5 moyennes sur 7, il investit 5/7 de la
part. S'il est au-dessus d'aucune, la part reste en cash.

**Le but n'est pas de gagner chaque jour.** Le but est d'être investi quand le
marché monte, de sortir quand il baisse, et donc d'éviter les grosses chutes.

## Résultats mesurés (données réelles, 2025-06 → 2026-11, frais de 0,2 %/ordre)

| | Gain total | Pire baisse | Mois positifs |
|---|---|---|---|
| **Ce bot** (BTC + ETH + or, ensemble SMA) | **+6,1 %** | **-11,7 %** | 47 % |
| Acheter et garder BTC + ETH + or | -2,5 % | -44,2 % | 47 % |
| Option 4 marchés (+ Nasdaq) | +5,0 % | -9,9 % | 41 % |
| Acheter et garder le Bitcoin seul | -29,2 % | -53,0 % | 41 % |

- Sous-périodes : -0,1 % (développement), +6,2 % (validation). Il n'est donc
  **pas** positif partout.
- Rejeu du bot jour par jour depuis 2025-10 : 500 € → 515,07 € (+3,0 %), pire
  baisse -11,3 %. Environ 9 ordres par mois (~44 € en médiane), ~12 € de frais au
  total.

**À lire avant de mettre de l'argent :**
1. L'historique ne couvre que 16 mois. C'est trop court pour conclure. Le
   résultat attendu est de quelques % par an, avec des mois perdants.
2. **Les frais décident de tout.** À 0,5 % par ordre, le résultat tombe à -1 %.
   À 1 % (le tarif crypto d'eToro), il tombe à environ -15 %. Il faut un exchange
   à ~0,1 % (Binance spot).
3. L'avantage principal, c'est la protection contre les chutes (pertes maximales
   divisées par 3). Ce n'est pas une machine à profit.
4. Les stratégies testées et écartées (moins bonnes ou instables) : RSI court
   terme, cassure Donchian, croisement EMA, et une seule moyenne mobile (le
   résultat dépendait trop du nombre de jours choisi). Pour tout revoir :
   `python research.py`.

## Vérification indépendante
`python crosscheck.py` recalcule les stratégies avec la bibliothèque open source
[backtesting.py](https://github.com/kernc/backtesting.py). Sur les 8 combinaisons
testées, les deux moteurs concordent à 0,1 point près (BTC SMA50 : -6,6 % / -6,6 % ;
or SMA50 : +31,6 % / +31,6 %...).

## Automatisation GitHub Actions
- `ci.yml`, job `trading-bot` : à chaque push, lance les tests, le rejeu et le
  contrôle croisé.
- `trading-bot-paper.yml` : simulation chaque jour à 00:23 UTC, avec les prix
  publics de Kraken. Les résultats sont enregistrés dans `paper_kraken/` :
  `equity.csv` pour la courbe, `trades.csv` pour les ordres. Aucune clé API,
  aucun argent réel. **GitHub ne lance ce workflow que depuis la branche `main`** :
  il faut donc merger d'abord. Lancement manuel possible via l'onglet Actions →
  « Run workflow ».

## Changer la stratégie : la règle
Toute variante doit passer `walkforward.py` : réglage choisi sur le passé seulement,
jugé sur la période suivante jamais vue, fenêtre après fenêtre, frais compris. Elle
n'est retenue que si elle bat la stratégie actuelle sur au moins 60 % des fenêtres
**et** au total, **et** pour au moins 75 % des 16 tailles de fenêtres testées.
Exemple (7 nov. 2026) : « meilleure moyenne mobile du moment » gagnait avec un réglage
de fenêtres et perdait avec la plupart des autres (4/16) : rejetée.

Chaque ordre du journal (`trades.csv`) indique sa raison : signal et cible, ou arrêt d'urgence.

## Installation
```bash
pip install -r requirements.txt
python -m pytest -q tests        # 10 tests : pas de lecture du futur, frais, arrêt d'urgence...
python bot.py --replay           # rejoue le bot sur l'historique local
```

## Étape 1 — Simulation (au moins 4 à 8 semaines)
```bash
python bot.py        # simulation : aucun argent réel, l'état est dans state.json
```
Lancement automatique chaque jour avec cron (00:05 UTC) :
```
5 0 * * * cd /chemin/trading_bot && python bot.py >> bot.log 2>&1
```

## Étape 2 — Argent réel (seulement si l'étape 1 est concluante)
1. Ouvre un compte Binance. Mets les 500 € en USDC.
2. Crée une clé API avec **uniquement « Spot trading » activé. Retraits DÉSACTIVÉS.**
   Restreins-la à ton adresse IP.
3. Lance :
```bash
export BOT_API_KEY=...  BOT_API_SECRET=...
export BOT_EXCHANGE=binance  BOT_QUOTE=USDC
python bot.py --live
```
Le bot vérifie que les paires (BTC/USDC, ETH/USDC, PAXG/USDC) existent avant de
trader, et refuse de démarrer sinon.

## Sécurités intégrées
- Simulation par défaut. Le mode réel exige `--live` **et** les clés API.
- **Approbation avant chaque ordre réel** : en `--live`, le bot affiche les ordres prévus et
  attend que tu tapes `OUI`. Sans terminal (tâche automatique), la réponse est non.
  `--yes` supprime la question : à réserver à une installation automatique de confiance.
- **Contrôle des tailles** : tout achat supérieur à 40 % du capital est bloqué (la stratégie
  n'en demande jamais plus d'un tiers ; au-delà c'est un bug ou un prix faux). Les ventes ne
  sont jamais bloquées, pour que l'arrêt d'urgence puisse toujours tout vendre.
- **Arrêt d'urgence** : si le capital baisse de 20 % depuis son plus haut, le
  bot vend tout et ne trade plus. Pour le relancer, il faut modifier `state.json`
  à la main (`"halted": false`).
- N'utilise que des bougies journalières clôturées.
- Ne trade une part que si elle s'écarte de plus de 5 % de sa cible, pour limiter les frais.
- Pas de levier, pas de vente à découvert.

## Fichiers
- `strategies.py` — les signaux
- `backtest.py` — moteur de test (signal à la clôture, exécution à l'ouverture suivante, frais)
- en simulation, `bot.py` exécute au prix d'ouverture du jour (comme le backtest), même si GitHub lance le passage avec des heures de retard ; en réel, au prix du moment
- `research.py`, `portfolio.py` — comparaison de toutes les stratégies
- `bot.py` — le bot (simulation / réel / rejeu)
- `data/` — historique journalier (source : TraderWAI)
