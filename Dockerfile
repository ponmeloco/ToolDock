FROM python:3.11-slim

# Verhindert, dass Python .pyc Dateien schreibt und sorgt für sofortige Log-Ausgabe
ENV PYTHONUNBUFFERED=1

# Umgebungsvariablen für npm (erlaubt npx Installationen ohne Root im Home-Verzeichnis)
ENV NPM_CONFIG_PREFIX=/home/appuser/.npm-global
ENV PATH=$PATH:/home/appuser/.npm-global/bin

WORKDIR /app

# 1. System-Abhängigkeiten & aktuelles Node.js (Version 20) installieren
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 2. Python-Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Anwendungs-Code kopieren
COPY . .

# 4. User anlegen und die komplette npm-Struktur vorbereiten
# Wir erstellen lib und bin vorab, damit npx sofort die richtige Umgebung vorfindet
RUN useradd -m appuser && \
    mkdir -p /home/appuser/.npm-global/lib && \
    mkdir -p /home/appuser/.npm-global/bin && \
    chown -R appuser:appuser /app /home/appuser

# Zum Non-Root User wechseln
USER appuser

# Ports für OpenAPI (8006) und MCP (8007)
EXPOSE 8006 8007

# Server starten
CMD ["python", "main.py"]
