# ig-stats-notifier

Στέλνει καθημερινά στο Telegram, στις 09:00 ώρα Ελλάδας, τα followers και
τα views των τελευταίων reels για μια λίστα Instagram accounts, μαζί με το
καλύτερο reel της ημέρας. Τρέχει εξ ολοκλήρου μέσω **GitHub Actions** — δεν
χρειάζεται το PC σου να είναι ανοιχτό.

## 1. API: Instagram Looter2 (RapidAPI)

Χρειάζεται δικό του subscription στο RapidAPI (ξεχωριστό από όποιο άλλο IG
API χρησιμοποιείς ήδη):

1. Πήγαινε στη σελίδα του
   [Instagram Looter2](https://rapidapi.com/irrors-apis/api/instagram-looter2)
   στο RapidAPI και κάνε subscribe σε ένα plan (το δωρεάν plan έχει όριο
   **150 requests/μήνα**· με followers+views καθημερινά για 4 accounts
   καταναλώνονται ~240/μήνα, άρα το δωρεάν plan θα εξαντλείται πριν το τέλος
   του μήνα — πρόσθεσε τότε ένα νέο/αναβαθμισμένο key στο `RAPIDAPI_KEY`
   secret).
2. Πάρε το **X-RapidAPI-Key** από το dashboard/app σου (πρέπει να είναι το
   key που είναι πραγματικά συνδεδεμένο με το subscription — αν έχεις
   πολλά "Applications" στο RapidAPI, βεβαιώσου ότι διαλέγεις το σωστό).

## 2. Telegram bot

1. Στο Telegram, μήνυμα στο **@BotFather** → `/newbot` → ακολούθησε τα
   βήματα → κράτα το **bot token** που σου δίνει.
2. Στείλε οποιοδήποτε μήνυμα στο νέο σου bot (π.χ. "hi") για να ανοίξεις
   συνομιλία μαζί του — αλλιώς δεν μπορεί να σου στείλει μηνύματα.
3. Άνοιξε στον browser:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   και βρες το `message.chat.id` στο JSON που θα δεις — αυτό είναι το
   `TELEGRAM_CHAT_ID`.

## 3. Τοπικό test (πριν το push)

```bash
cd ig-stats-notifier
pip install -r requirements.txt
cp .env.example .env
# συμπλήρωσε RAPIDAPI_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID στο .env
python notifier.py
```

Αν όλα πάνε καλά θα δεις ένα μήνυμα να φτάνει στο Telegram και θα
ενημερωθεί το `state.json` τοπικά.

## 4. GitHub setup

1. Κάνε το repo push σε ένα **private** GitHub repo (περιέχει follower
   data για τα accounts σου).
2. Settings → Secrets and variables → Actions → **Secrets** tab → πρόσθεσε:
   - `RAPIDAPI_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. (Προαιρετικό) ίδιο μενού, **Variables** tab, αν θες να αλλάξεις τα
   defaults χωρίς να αγγίξεις τον κώδικα:
   - `IG_USERNAMES` (default: οι 4 λογαριασμοί μέσα στο `notifier.py`)
4. Tab **Actions** → επίλεξε το workflow "Daily IG stats to Telegram" →
   **Run workflow** για δοκιμή χωρίς να περιμένεις το πρωινό cron.

## Ωράριο & DST caveat

Το cron (`.github/workflows/daily-stats.yml`) είναι ορισμένο για
`06:00 UTC` = 09:00 ώρα Ελλάδας το καλοκαίρι (EEST, UTC+3). Τον Οκτώβριο,
όταν η Ελλάδα γυρνάει σε χειμερινή ώρα (EET, UTC+2), το μήνυμα θα φτάνει
στις 08:00 αντί 09:00, εκτός αν αλλάξεις το cron σε `0 7 * * *` χειμερινά
(και το ξαναγυρίσεις σε `0 6 * * *` την άνοιξη).

## Request budget (RapidAPI free plan, 150/μήνα)

- Followers (`/profile`) + views (`/reels`): 2 calls/account/μέρα × 4
  accounts × ~30 μέρες ≈ **~240/μήνα** — ξεπερνάει το δωρεάν όριο πριν το
  τέλος του μήνα. Αποδεκτό tradeoff (καθημερινά followers > οικονομία
  requests) — απλά περίμενε να χρειαστεί rotation του `RAPIDAPI_KEY`
  secret μέσα στον μήνα.

## Αρχεία

- `notifier.py` — όλη η λογική (fetch stats, υπολογισμός delta, αποστολή
  Telegram).
- `state.json` — snapshot της τελευταίας γνωστής τιμής ανά account (commit
  πίσω στο repo αυτόματα από το ίδιο το GitHub Action μετά από κάθε run).
- `.github/workflows/daily-stats.yml` — το cron.
