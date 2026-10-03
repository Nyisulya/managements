# Mifumo Yangu &bull; Central SaaS Subscription & Billing Manager

Mfumo madhubuti wa usimamizi wa wateja (Makanisa, Maofisi, Shule, Kliniki, n.k.) uliotengenezwa kwa **Django**. Unakuwezesha kufuatilia tarehe za kuisha, kutuma barua pepe za vikumbusho zikiwa na **Link ya Mfumo wa Mteja**, kuwawezesha kulipia kwa simu (**M-Pesa, Tigo Pesa, Airtel Money na HaloPesa**) kupitia **HarakaPay API**, na kuongeza siku zao za leseni moja kwa moja.

Hakuna haja ya kuunganisha API ngumu kwenye mifumo ya wateja—kila mteja anahifadhiwa na link yake ya mfumo, na unaweza kumsimamisha moja kwa moja kwenye aaPanel kwa kubonyeza kitufe kimoja muda ukipita.

---

## 🌟 Vipengele Vikuu (Key Features)

1. **Dashboard ya Kisasa & Mobile-Friendly:**
   - Inaendana kikamilifu na simu na kompyuta (Bottom Navigation bar kwenye simu, Off-canvas drawer).
   - Inaonyesha hesabu ya **MRR (Monthly Recurring Revenue)**, makusanyo ya mwezi huu, na idadi ya wateja kulingana na hali zao (**Hai**, **Wanaokaribia Kuisha**, **Walioisha**).
   - Orodha ya wateja ikiwa na **Link ya Moja kwa Moja ya Mfumo wao** (Direct Live System Link), Siku Zilizobaki, na vitufe vya haraka (+Siku, Tuma Email, Nakili Pay Link).

2. **Self-Service Checkout Portal (`/pay/<slug>/`):**
   - Kila mteja ana link yake ya kipekee (mf. `https://mifumo.yako.com/pay/kkkt-mwenge/`).
   - Mteja anachagua kifurushi, anaweka namba yake ya simu, na kubonyeza **"Lipia Sasa (USSD Push)"**.
   - HarakaPay inatuma USSD Push ya PIN kwenye simu ya mteja.
   - Mfumo unakagua malipo mubashara (Live Polling bila ku-refresh). Mteja akilipa, siku zinaongezwa papo hapo na risiti inatumwa kwenye barua pepe yake.

3. **Uwasilishaji wa Barua Pepe (Email Delivery):**
   - Jina la mtumaji: **Felician <info@nyisu.com>**.
   - Injini kuu: **Resend API** (100% Inbox delivery bila kuangukia spam).
   - Backup: **Gmail SMTP** (inatumika iwapo Resend ikipata hitilafu yoyote).
   - Kila barua pepe ina jina la mteja, siku zilizobaki, **Link ya Mfumo wa Mteja**, na kitufe cha kufungua mfumo wake moja kwa moja.

4. **Usimamizi wa aaPanel Rahisi:**
   - Dashboard inakupa muongozo wa haraka na link ya kufungua mfumo wa mteja.
   - Ukiona mteja hajalipa, unaenda kwenye aaPanel na kusimamisha tovuti au app yake kwa kitufe kimoja tu cha **Stop/Pause**.

---

## 🚀 Muongozo Kamili wa Kupandisha Kwenye VPS / aaPanel (Deployment Guide)

### Hatua ya 1: Panda Faili Kwenye VPS
Unaweza kutumia Git au ku-zip mradi na kupakia kwenye aaPanel File Manager:
```bash
# Ingia kwenye VPS kupitia SSH au aaPanel Terminal:
cd /www/wwwroot/
git clone <link-ya-repo-yako> mifumo-yangu
cd mifumo-yangu
```

### Hatua ya 2: Fungua Virtual Environment na Sakinisha Mahitaji
```bash
# Fungua Python 3 virtual environment
python3 -m venv venv
source venv/bin/activate

# Sakinisha libraries zote zinazohitajika
pip install --upgrade pip
pip install -r requirements.txt
```

### Hatua ya 3: Weka Faili ya Mipangilio (`.env`)
Nakili faili ya `.env.example` kuwa `.env`:
```bash
cp .env.example .env
nano .env
```
Hakikisha:
- `DEBUG=False`
- `ALLOWED_HOSTS=*` (au weka domain yako mfano `mifumo.nyisu.com`)
- `BASE_URL=https://domain-yako.com`
- `CSRF_TRUSTED_ORIGINS=https://domain-yako.com,https://harakapay.net`
- Taarifa za HarakaPay na Resend zipo tayari.

### Hatua ya 4: Endesha Database Migrations na Kusanya Static Files
```bash
python manage.py migrate
python manage.py collectstatic --noinput

# Tengeneza akaunti ya Admin (kama haipo au unataka mpya):
python manage.py createsuperuser
```
*(Kumbuka akaunti ya mfano iliyopo: username `admin`, password `admin123`).*

---

### Hatua ya 5: Kuendesha Mradi Kwenye aaPanel (Njia Rahisi Zaidi)

#### Chaguo A: Kutumia aaPanel "Python Project Manager"
1. Kwenye aaPanel, nenda **App Store** -> Sakinisha **Python Project Manager**.
2. Fungua **Python Project Manager** -> Bonyeza **Add Project**:
   - **Project Name:** `mifumo_yangu`
   - **Path:** `/www/wwwroot/mifumo-yangu`
   - **Python Version:** Chagua Python 3.10 / 3.11 / 3.12
   - **Framework:** `Django`
   - **Startup File:** `core/wsgi.py` au tumia Gunicorn
   - **Processes:** `2` au `4`
   - **Port:** `8000` (au port yoyote iliyo wazi)
3. Bonyeza **Submit**. Mradi utawashwa mara moja!

#### Chaguo B: Kutumia Gunicorn & Systemd (Njia ya Kawaida ya Linux)
1. Fungua faili ya service:
   ```bash
   sudo nano /etc/systemd/system/mifumo.service
   ```
2. Weka mistari ifuatayo:
   ```ini
   [Unit]
   Description=Mifumo Yangu Django Gunicorn Daemon
   After=network.target

   [Service]
   User=www
   Group=www
   WorkingDirectory=/www/wwwroot/mifumo-yangu
   ExecStart=/www/wwwroot/mifumo-yangu/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 core.wsgi:application
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
3. Washa na uanze service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start mifumo
   sudo systemctl enable mifumo
   ```

---

### Hatua ya 6: Kuunganisha Domain & Nginx Kwenye aaPanel
1. Kwenye aaPanel, nenda **Website** -> Bonyeza **Add Site**.
2. Weka **Domain Name** yako (mfano `mifumo.domainyako.com`).
3. Bonyeza **Submit**.
4. Bonyeza tovuti hiyo -> Nenda kwenye **Reverse Proxy** -> Bonyeza **Add Reverse Proxy**:
   - **Proxy Name:** `django_proxy`
   - **Target URL:** `http://127.0.0.1:8000`
   - **Sent Domain:** `$host`
   - Bonyeza **Save**.
5. Kwenye menu ya tovuti hiyo, nenda **SSL** -> Washa **Let's Encrypt** (bila malipo) ili kupata `https://`.
6. Weka static files zionekane vizuri kwa kuongeza kwenye Nginx Config ya tovuti hiyo:
   ```nginx
   location /static/ {
       alias /www/wwwroot/mifumo-yangu/staticfiles/;
       expires 30d;
   }
   ```

---

### Hatua ya 7: Kuweka Cron Job ya Kutuma Vikumbusho Kiotomatiki
Kwenye aaPanel, nenda **Cron**:
- **Type of Task:** `Shell Script`
- **Name of Task:** `Mifumo Reminders Cron`
- **Period:** Kila siku saa 02:00 asubuhi (Every Day `08:00 AM`)
- **Script Content:**
  ```bash
  cd /www/wwwroot/mifumo-yangu
  /www/wwwroot/mifumo-yangu/venv/bin/python manage.py send_reminders
  ```
- Bonyeza **Add Task**.

Hapo mfumo utakuwa unakagua wateja wote kila siku asubuhi, na wanaokaribia kuisha watatumiwa barua pepe za kikumbusho zenye link ya mifumo yao na link ya kulipia moja kwa moja!

---

## 🔑 Akaunti ya Kuingilia Kwenye Dashboard
- **URL:** `https://domain-yako.com/login/`
- **Username:** `admin`
- **Password:** `admin123`
*(Kumbuka kubadili nenosiri hili baada ya kuingia).*
