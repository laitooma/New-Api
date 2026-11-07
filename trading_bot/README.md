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

## Installation
```bash
pip install -r requirements.txt
python -m pytest -q tests        # 9 tests : pas de lecture du futur, frais, arrêt d'urgence...
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
- **Arrêt d'urgence** : si le capital baisse de 20 % depuis son plus haut, le
  bot vend tout et ne trade plus. Pour le relancer, il faut modifier `state.json`
  à la main (`"halted": false`).
- N'utilise que des bougies journalières clôturées.
- Ne trade une part que si elle s'écarte de plus de 5 % de sa cible, pour limiter les frais.
- Pas de levier, pas de vente à découvert.

## Fichiers
- `strategies.py` — les signaux
- `backtest.py` — moteur de test (signal à la clôture, exécution à l'ouverture suivante, frais)
- `research.py`, `portfolio.py` — comparaison de toutes les stratégies
- `bot.py` — le bot (simulation / réel / rejeu)
- `data/` — historique journalier (source : TraderWAI)
