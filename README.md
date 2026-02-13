# Network & Sensor Stability Monitor

Diagnostický nástroj pro Raspberry Pi, který měří stabilitu WiFi připojení a dostupnost IoT senzorů v lokální síti. Generuje detailní HTML reporty s Plotly grafy, korelační analýzou a doporučeními.

## Funkce

- **WiFi diagnostika** — RSSI, link quality, detekce odpojení, změn IP adresy
- **Síťová konektivita** — ping na gateway a internet, latence, jitter, packet loss
- **Monitoring senzorů** — ping, MQTT, HTTP health check pro každé IoT zařízení
- **Korelační analýza** — rozliší, zda je problém ve WiFi nebo v konkrétním senzoru
- **Klasifikace incidentů** — WiFi outage, degradace, internet outage, sensor outage
- **HTML reporty** — Plotly grafy, tabulky, doporučení, hodnocení A–F
- **Live konzolový výstup** — aktuální stav přes `rich` knihovnu
- **SQLite databáze** — persistentní ukládání metrik s konfigurovatelnou retencí

## Rychlý start (Docker)

### 1. Příprava konfigurace

```bash
cp config.example.yml config.yml
```

Upravte `config.yml` pro vaše prostředí — nastavte IP gateway, IP adresy senzorů, WiFi interface atd.

### 2. Spuštění

```bash
docker compose up -d
```

### 3. Sledování logů

```bash
docker compose logs -f
```

### 4. Reporty

Reporty se automaticky generují do adresáře `./reports/`. Otevřete HTML soubor v prohlížeči.

## Ruční spuštění (bez Dockeru)

### Požadavky

- Python 3.11+
- Linux s WiFi rozhraním (Raspberry Pi OS)
- Nainstalované systémové nástroje: `ping`, `iw`, `iwconfig`, `ip`

### Instalace

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Spuštění monitoringu

```bash
# Monitoring po dobu 24 hodin
python monitor.py --config config.yml --duration 24h

# Kontinuální monitoring (Ctrl+C pro zastavení)
python monitor.py --config config.yml --duration continuous

# Krátký test (2 hodiny)
python monitor.py --config config.yml --duration 2h
```

### Generování reportu z existujících dat

```bash
# Report za posledních 24 hodin
python generate_report.py --config config.yml

# Report za posledních 7 dní
python generate_report.py --config config.yml --period 7d

# Report s vlastním výstupem
python generate_report.py --config config.yml --output ./my_report.html
```

## Konfigurace

Viz `config.example.yml` s komentáři. Hlavní sekce:

| Sekce | Popis |
|---|---|
| `wifi` | Interface, interval kontroly, RSSI thresholdy |
| `gateway` | IP adresa routeru, ping interval |
| `internet_targets` | IP adresy pro ověření konektivity ven (8.8.8.8, 1.1.1.1) |
| `sensors` | Seznam IoT zařízení (name, ip, type: ping/mqtt/http) |
| `monitoring` | Délka měření, interval reportů, retence dat |
| `database` | Cesta k SQLite databázi |
| `report` | Výstupní adresář, timezone |
| `logging` | Úroveň logování, soubor, rotace |

### Env proměnné

MQTT credentials lze zadat přes environment variables (viz `.env.example`):

```bash
MQTT_USERNAME=mqtt_user
MQTT_PASSWORD=mqtt_pass
TZ=Europe/Prague
```

## Docker deployment na Raspberry Pi

### Předpoklady

```bash
# Instalace Dockeru na RPi
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Odhlaste se a přihlaste znovu

# Ověření
docker --version
docker compose version
```

### Deployment

```bash
git clone <repo-url> ~/network-monitor
cd ~/network-monitor

# Konfigurace
cp config.example.yml config.yml
nano config.yml          # upravte pro vaše prostředí

cp .env.example .env
nano .env                # nastavte timezone

# Build a spuštění
docker compose up -d

# Ověření
docker compose ps
docker compose logs -f
```

### Přístup k reportům

Reporty se ukládají do `./reports/` na hostiteli. Pro zobrazení přes webový prohlížeč můžete použít jednoduchý HTTP server:

```bash
cd reports && python3 -m http.server 8080
```

Poté otevřete `http://<rpi-ip>:8080` v prohlížeči.

## Struktura HTML reportu

1. **Souhrnná sekce** — WiFi uptime %, hodnocení A–F, počet incidentů
2. **WiFi analýza** — graf RSSI v čase s barevnými zónami, timeline stavů
3. **Síťová konektivita** — latence gateway vs internet, packet loss
4. **Senzory** — tabulka dostupnosti, timeline dostupnosti všech senzorů
5. **Incidenty** — timeline, detaily, klasifikace příčiny
6. **Doporučení** — automaticky generovaná na základě dat

## Klasifikace incidentů

| Typ | Popis |
|---|---|
| `wifi_outage` | WiFi interface odpojeno nebo gateway nedostupná |
| `wifi_degradation` | Slabý signál (RSSI pod threshold) nebo vysoký packet loss |
| `internet_outage` | Gateway ok, ale internet nedostupný |
| `sensor_outage` | Konkrétní senzor nedostupný (rozliší WiFi vs senzor problém) |
| `full_outage` | Kompletní výpadek všeho |

## Struktura projektu

```
├── monitor.py              # Hlavní CLI - spouštění monitoringu
├── generate_report.py      # CLI - generování reportu z DB
├── config.example.yml      # Vzorová konfigurace
├── requirements.txt        # Python závislosti
├── Dockerfile              # Docker image (ARM64 compatible)
├── docker-compose.yml      # Docker Compose (host network)
├── .env.example            # Vzorové env proměnné
└── src/
    ├── monitor.py          # Hlavní aplikace (NetworkMonitorApp)
    ├── report_generator.py # HTML report generátor (Plotly + Jinja2)
    ├── models/
    │   ├── schema.py       # SQLAlchemy modely (WiFiMetric, PingResult, ...)
    │   └── database.py     # Database operations
    ├── monitors/
    │   ├── wifi_monitor.py     # WiFi diagnostika (iwconfig, iw, /proc)
    │   ├── network_monitor.py  # Ping a DNS monitoring
    │   └── sensor_monitor.py   # Senzor checks (ping, MQTT, HTTP)
    ├── utils/
    │   ├── config.py           # YAML config loading
    │   ├── incident_detector.py # Detekce a korelace incidentů
    │   └── recommendations.py  # Automatická doporučení
    └── templates/
        └── report_template.html # Jinja2 HTML šablona
```

## Licence

MIT
