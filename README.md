# claude-dashboard

Web-dashboard для [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — просмотр memory-файлов и истории сессий через браузер. Один файл на Python, ноль зависимостей, Docker-ready.

```
Memory: sidebar с группировкой по типам, markdown-рендеринг, поиск
Sessions: таблица всех сессий, полнотекстовый поиск, drawer с логом диалога
Auth: логин/пароль, cookie-сессии
```

## Возможности

- **Memory viewer** — все `.md` файлы из memory-директории, сгруппированы по типам (user, feedback, project, reference), переключение rendered/raw, поиск
- **Sessions** — таблица всех сессий Claude Code с сортировкой, полнотекстовый поиск по всем сообщениям (не только first/last), кнопка копирования `cd + claude --resume` команды
- **Session drawer** — клик по строке открывает панель справа с полным логом диалога, подсветка найденных слов при активном поиске
- **Один файл** — весь код, шаблоны, стили и JS в `server.py` (~30KB)
- **Ноль зависимостей** — только Python stdlib, никакого `pip install`
- **Конфигурация через env** — пароль, порт, пути, SSL — всё через переменные окружения

## Быстрый старт

### Docker Compose

```bash
git clone https://github.com/ZombiePm/claude-dashboard.git
cd claude-dashboard
cp .env.example .env
# Отредактируйте .env — как минимум AUTH_PASS
docker compose up -d
```

Открыть `http://localhost:8080`

### Без Docker

```bash
git clone https://github.com/ZombiePm/claude-dashboard.git
cd claude-dashboard
export AUTH_PASS=your-password
export USE_SSL=0
python3 server.py
```

Открыть `http://localhost:8080`

## Конфигурация

Копируйте `.env.example` → `.env` и настройте:

```bash
# Сервер
BIND=0.0.0.0
PORT=8080
USE_SSL=0

# Авторизация
AUTH_USER=admin
AUTH_PASS=changeme

# Данные (пути к Claude Code)
MEMORY_DIR=/root/MEMORY
HISTORY_FILE=/root/.claude/history.jsonl

# SSL (при USE_SSL=1)
# CERT_FILE=cert.pem
# KEY_FILE=key.pem

# Нормализация путей Windows → Linux
# NORM_PATH_MAP=C:/Users/me=/home/me
```

Все параметры:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BIND` | `0.0.0.0` | Адрес прослушивания |
| `PORT` | `8080` | Порт |
| `USE_SSL` | `1` | `1` — HTTPS, `0` — HTTP |
| `CERT_FILE` | `cert.pem` | SSL сертификат |
| `KEY_FILE` | `key.pem` | SSL ключ |
| `MEMORY_DIR` | `/root/MEMORY` | Директория с memory-файлами |
| `HISTORY_FILE` | `/root/.claude/history.jsonl` | Файл истории сессий |
| `AUTH_USER` | `admin` | Логин |
| `AUTH_PASS` | `changeme` | Пароль |
| `NORM_PATH_MAP` | _(пусто)_ | Маппинг путей (см. ниже) |

## Интеграция в существующий compose

```yaml
  claude-dashboard:
    build: /path/to/claude-dashboard
    container_name: claude-dashboard
    restart: unless-stopped
    volumes:
      - /path/to/memory:/data/memory:ro
      - /path/to/history.jsonl:/data/history.jsonl:ro
    environment:
      BIND: "0.0.0.0"
      PORT: "80"
      USE_SSL: "0"
      MEMORY_DIR: /data/memory
      HISTORY_FILE: /data/history.jsonl
      AUTH_USER: admin
      AUTH_PASS: your-password
```

За reverse proxy (NPM, nginx, Traefik): upstream `claude-dashboard:80`, scheme `http`.

## SSL

Для standalone-режима с HTTPS:

```bash
# Генерация самоподписанного сертификата
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 365 -nodes -subj '/CN=localhost'

export USE_SSL=1
python3 server.py
```

## Systemd

```ini
[Unit]
Description=Claude Dashboard
After=network.target

[Service]
Type=simple
EnvironmentFile=/opt/claude-dashboard/.env
ExecStart=/usr/bin/python3 /opt/claude-dashboard/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Нормализация путей

Сессии хранят пути проектов с машины, где запускался Claude Code. Если Claude Code работал на Windows, а dashboard крутится на Linux — пути не совпадут. `NORM_PATH_MAP` решает это:

```bash
# Windows → Linux
NORM_PATH_MAP=C:/Users/me=/home/me,D:/projects=/srv/projects

# UNC → Linux
NORM_PATH_MAP=//server/share=/mnt/share
```

## Источники данных

Dashboard читает два источника (**read-only**):

**Memory** — директория с `.md` файлами. Опциональный YAML frontmatter:

```markdown
---
name: Server Config
description: Production server configuration notes
type: project
---

Content here...
```

**history.jsonl** — история сессий Claude Code, по одной JSON-строке:

```json
{"display": "текст сообщения", "timestamp": 1234567890000, "sessionId": "uuid", "project": "/path"}
```

## Структура

```
claude-dashboard/
├── server.py            # Всё приложение
├── Dockerfile           # python:3.12-slim
├── docker-compose.yml   # Быстрый старт
├── .env.example         # Шаблон конфигурации
└── .gitignore
```

## Требования

| Компонент | Минимум |
|---|---|
| Python | 3.10+ |
| Docker | 20+ (опционально) |
| Диск | ~1 MB (сам dashboard) |
| RAM | ~30 MB |

## Support

Если проект оказался полезен:

| Network  | Address |
|----------|---------|
| **SOL**  | `BMvNKNK7zTRc6jQsdyUKFE6wFL6TJMKL1ZSRhW6pCpNJ` |
| **ETH**  | `0x743d66E349270355200b958FC1caC8427a9efe04` |
| **BTC**  | `bc1qset463vqdydrgpxy4m5hvke0cqvtlqztqrqw2v` |
