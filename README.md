# WebOps Voice Service

🎤 **Inteligentna usługa głosowa do automatyzacji operacji DevOps zasilana przez NLP2CMD**

## 🌟 Przegląd

WebOps Voice Service to nowoczesna aplikacja webowa, która pozwala na sterowanie operacjami systemowymi za pomocą komend głosowych i tekstowych. Wykorzystuje pakiet NLP2CMD do przetwarzania języka naturalnego na komendy shell.

### ✨ Kluczowe Funkcje

- 🎤 **Voice Control** - Wspieranie komend głosowych (placeholder)
- ⌨️ **Text Input** - Precyzyjne komendy tekstowe
- 🤖 **NLP2CMD Integration** - Przetwarzanie języka naturalnego na komendy
- 🐳 **Docker Ready** - Pełna konteneryzacja
- 📊 **Real-time Logs** - Live podgląd wykonania komend
- 🌐 **Modern Web UI** - Intuicyjny interfejs webowy
- 🔒 **Safe Execution** - Izolowane środowisko wykonania
- 📈 **Metrics Dashboard** - Statystyki wydajności

## 🚀 Szybki Start

### Wymagania

- Docker & Docker Compose
- Python 3.11+ (dla developmentu)

### Instalacja i Uruchomienie

```bash
# Klonuj repozytorium
git clone https://github.com/wronai/nlp2cmd.git
cd nlp2cmd/webops

# Uruchom serwis
./setup.sh
```

### Ręczna Instalacja

```bash
# Zbuduj obraz Docker
docker build -f Dockerfile.submodule -t webops-voice:latest .

# Uruchom kontener
docker run -d --name webops-voice -p 8001:8001 webops-voice:latest

# Lub użyj Docker Compose
docker compose up -d
```

## 🌐 Dostęp

- **Web Interface**: http://localhost:8001
- **API Endpoint**: http://localhost:8001/voice-command
- **Health Check**: http://localhost:8001/health

## 📋 Przykładowe Komendy

### Zarządzanie Plikami
- "list files in current directory" → `ls -la`
- "find files larger than 100MB" → `find . -type f -size +100M`
- "create backup of config files" → `cp *.conf backup/`

### Monitorowanie Systemu
- "show system processes" → `ps aux`
- "check disk space usage" → `df -h`
- "show network connections" → `netstat -tuln`

### DevOps Operacje
- "list running Docker containers" → `docker ps`
- "show system logs" → `tail -f /var/log/syslog`
- "check service status" → `systemctl status`

## 🔧 API

### Voice Command Endpoint

```bash
curl -X POST http://localhost:8001/voice-command \
  -H "Content-Type: application/json" \
  -d '{
    "text_command": "list files in current directory",
    "language": "pl",
    "execute": true
  }'
```

### Response Format

```json
{
  "success": true,
  "command": "ls -la",
  "explanation": "Generated command: ls -la",
  "confidence": 0.85,
  "execution_result": {
    "success": true,
    "exit_code": 0,
    "stdout": "total 92\ndrwxr-xr-x...",
    "stderr": "",
    "logs": ["total 92", "drwxr-xr-x..."]
  },
  "logs": ["total 92", "drwxr-xr-x..."],
  "error": null
}
```

## 🏗️ Architektura

### Komponenty

1. **Voice Service** - Główna aplikacja FastAPI
2. **NLP2CMD Integration** - Przetwarzanie języka naturalnego
3. **Shell Executor** - Bezpieczne wykonanie komend
4. **WebSocket Server** - Real-time log streaming
5. **Web UI** - Nowoczesny interfejs użytkownika

### Struktura Projektu

```
webops/
├── voice_service.py          # Główna aplikacja FastAPI
├── docker_app.py             # Oryginalna aplikacja Docker
├── Dockerfile.submodule      # Konfiguracja build z NLP2CMD
├── docker-compose.yml        # Orkiestracja kontenerów
├── setup.sh                  # Automatyczny setup
├── requirements.txt          # Zależności Python
├── requirements-voice.txt    # Zależności voice service
├── tests/                    # Testy jednostkowe i integracyjne
│   ├── test_voice_service.py
│   ├── test_docker.py
│   └── load_test.py
├── nlp2cmd-repo/             # Git submodule NLP2CMD
├── nginx/                    # Konfiguracja Nginx (opcjonalnie)
└── monitoring/               # Konfiguracja monitoringu (opcjonalnie)
```

## 🔒 Bezpieczeństwo

### Izolacja
- Konteneryzacja Docker
- Ograniczone uprawnienia użytkownika
- Izolowane środowisko wykonania

### Ograniczenia
- Limit czasu wykonania (30s)
- Filtracja niebezpiecznych komend
- Brak dostępu do systemowych plików

## 📊 Monitorowanie

### Health Check
```bash
curl http://localhost:8001/health
```

### Logi
```bash
# View container logs
docker logs -f webops-voice

# View application logs
tail -f logs/voice_service.log
```

### Metrics
- Liczba wykonanych komend
- Success rate
- Średni czas odpowiedzi
- Status serwisu

## 🛠️ Development

### Lokalne Uruchomienie

```bash
# Zainstaluj zależności
pip install -r requirements.txt
pip install -r requirements-voice.txt

# Uruchom serwis
python voice_service.py
```

### Testy

```bash
# Uruchom wszystkie testy
python -m pytest tests/

# Testy jednostkowe
python -m pytest tests/test_voice_service.py

# Testy Docker
python -m pytest tests/test_docker.py

# Load testing
python tests/load_test.py
```

### Konfiguracja

```bash
# Environment variables
export NLP2CMD_HOST=0.0.0.0
export NLP2CMD_PORT=8001
export NLP2CMD_DEBUG=false
export NLP2CMD_LOG_LEVEL=info
export NLP2CMD_AUTO_EXECUTE=true
export WORKSPACE_DIR=/app/workspace
```

## 🔄 Zarządzanie Serwisem

```bash
# Start
docker compose up -d

# Stop
docker compose down

# Restart
docker compose restart

# Rebuild
docker compose up -d --build

# Clean up
docker compose down -v
```

## 🐛 Troubleshooting

### Common Issues

1. **Port zajęty**
   ```bash
   # Znajdź proces na porcie
   lsof -i :8001
   # Zmień port w docker-compose.yml
   ```

2. **Błędy NLP2CMD**
   ```bash
   # Sprawdź logi
   docker logs webops-voice
   # Upewnij się że submodule jest zainicjowany
   git submodule update --init --recursive
   ```

3. **Brak uprawnień**
   ```bash
   # Sprawdź uprawnienia katalogów
   ls -la logs/ workspace/ uploads/
   ```

## 📈 Performance

### Optymalizacje
- Docker build caching
- Async processing
- Connection pooling
- Log buffering

### Metrics
- Response time: ~50ms
- Throughput: 100+ requests/min
- Memory usage: ~200MB
- CPU usage: ~5%

## 🤝 Współpraca

1. Fork projektu
2. Stwórz feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request

## 📄 Licencja

MIT License - zobacz plik LICENSE

## 🔗 Linki

- [NLP2CMD Repository](https://github.com/wronai/nlp2cmd)
- [Docker Hub](https://hub.docker.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

**WebOps Voice Service** - Przyszłość automatyzacji DevOps 🚀🎤
