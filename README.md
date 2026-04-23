# TrendBot

En enkel trendbot som:

- hämtar Google News RSS-sökresultat för valda topics
- hämtar extra RSS-källor för nyheter, underhållning, musik och internetkultur
- kan hämta Reddit-träffar för de första topics om du slår på det
- sparar historik i SQLite
- upptäcker spikes mot ett glidande snitt
- lyfter fram en konkret trendfras från rubrikerna i stället för bara ett generellt ämne
- klustrar liknande rubriker till samma story
- räknar top movers per kategori
- kör enkel backtesting av trendreglerna
- skickar alerts till Discord via webhook
- visar en lokal dashboard med daily top 10, category movers, topic clusters, grafer och senaste observationer

## Körning

Sätt miljövariabler:

- `TRENDBOT_TOPICS` = kommaseparerade topics, till exempel `pop culture,music,politics,news,movies,tv,celebrity,K-pop,Eurovision,TikTok,influencer,streamers,youtube,memes,viral trends,internet culture,creator economy,viral video,gaming,podcasts,streaming,fashion,sports`
- `TRENDBOT_BLOCKED_TERMS` = termer som aldrig ska trigga alerts, default `ai,openai,chatgpt,artificial intelligence,machine learning`
- `REDDIT_ENABLED` = sätt till `1` om du vill slå på Reddit igen, default `false`
- `REDDIT_TOPIC_LIMIT` = hur många topics som Reddit får läsa, default `5`
- `TRENDBOT_REDDIT_SUBREDDITS` = Reddit-subreddits som får användas för Reddit-fetchen, default popkultur-/underhållningsefterfrågan
- extra RSS-källor som används som standard är BBC Entertainment, NPR Music, AP Entertainment, Variety, Billboard och The Verge
- `ALERT_MIN_SOURCES` = minsta antal källor som måste trigga innan en alert skickas, default `2`
- `ALERT_RATIO_THRESHOLD` = minsta ratio för att en alert ska anses stark nog, default `2.5`
- `ALERT_COOLDOWN_SECONDS` = hur länge samma topic måste vila mellan alerts, default `3600`
- `DAILY_DIGEST_INTERVAL_SECONDS` = hur ofta daily top 10 skickas till Discord, default `86400`
- `DASHBOARD_ENABLED` = sätt till `1` för att starta den lokala dashboarden, default `false`
- `DASHBOARD_HOST` / `DASHBOARD_PORT` = adress för dashboarden, default `127.0.0.1:8000`
- `DISCORD_WEBHOOK_URL` = din Discord webhook-URL
- `POLL_INTERVAL_SECONDS` = pollingintervall, default `300`
- `HEARTBEAT_INTERVAL_SECONDS` = hur ofta boten skickar en live-heartbeat när det inte finns alerts, default `1800`
- `DEBUG_MODE` = skriv ut vilken topic som var närmast att trigga, default `false`

Valfria inställningar:

- `WINDOW_SIZE` = antal tidigare observationer för baseline, default `12`
- `SPIKE_MULTIPLIER` = hur stor spike som krävs, default `2.5`
- `MIN_BASELINE` = minsta baseline för att kunna larma, default `2`
- `POP_CULTURE_SPIKE_MULTIPLIER` = lättare tröskel för popkultur, default `2.0`
- `POP_CULTURE_MIN_BASELINE` = minsta baseline för popkultur, default `1`
- `REDDIT_LIMIT` = antal Reddit-resultat per topic, default `25`
- `REDDIT_SUBREDDITS` används genom `TRENDBOT_REDDIT_SUBREDDITS` och begränsar Reddit till popkulturrelaterade subreddits
- `GOOGLE_NEWS_HL` = språk för Google News, default `en-US`
- `GOOGLE_NEWS_GL` = land för Google News, default `US`
- `GOOGLE_NEWS_CEID` = Google News edition, default `US:en`
- `TRENDBOT_DB_PATH` = SQLite-fil, default `trendbot.sqlite3`

## Exempel

```bash
export TRENDBOT_TOPICS="pop culture,music,politics,news,movies,tv,celebrity,K-pop,Eurovision,TikTok,influencer,streamers,youtube,memes,viral trends,internet culture,creator economy,viral video,gaming,podcasts,streaming,fashion,sports"
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python3 main.py
```

För ett engångstest:

```bash
python3 main.py once
```

## Hur den fungerar

Trendbot räknar filtrerade Reddit-inlägg och Google News-träffar som matchar varje topic. Reddit-fetchen är begränsad till en lista med popkultur- och underhållningssubreddits, så den drar inte in hela Reddit-flödet. Boten jämför senaste mätningen mot ett snitt av tidigare mätningar och skickar en Discord-alert om aktiviteten sticker ut. När den larmar försöker den också plocka ut en mer exakt trendfras från rubrikerna, som `Olivia Rodrigo new album`, i stället för att bara säga en bred kategori. Google News prioriteras för etiketten när den finns, eftersom rubrikerna ofta är renare än Reddit.

Om ingen alert skickas under en körning och det har gått en timme sedan senaste heartbeat, skickar boten en liten Discord-statusrad som visar att den fortfarande kör. En gång per dygn kan den också skicka en daily top 10 till Discord, baserad på senaste 24 timmarna.

Om `DEBUG_MODE` är på skriver boten också ut vilken topic/source som var närmast att trigga under varje körning.

Om dashboarden är på får du ett lokalt gränssnitt på `http://127.0.0.1:8000` som visar daily top 10, category movers, topic clusters, grafer, backtesting och senaste observationer.

Om du vill kan du göra ämneslistan ännu mer specifik med saker som gaming, podcasts, memes, streaming, och creator culture utan att ändra resten av boten.
