#!/bin/bash
# ============================================================
# Скрипт инициализации Apache Superset
#
# Выполняется при первом запуске:
# 1. Применяет миграции БД
# 2. Создаёт администратора
# 3. Загружает примеры (опционально)
# ============================================================

set -e

echo "=== Ожидание готовности PostgreSQL ==="
# Ждём пока PostgreSQL станет доступен
# Используем python вместо nc, т.к. nc не установлен в образе Superset
while ! python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
s.connect(('superset_db', 5432))
s.close()
" 2>/dev/null; do
  echo "PostgreSQL ещё не готов, ждём..."
  sleep 2
done
echo "PostgreSQL доступен!"

echo "=== Применение миграций БД ==="
superset db upgrade

echo "=== Инициализация Superset ==="
superset init

echo "=== Создание администратора ==="
# Создаём пользователя admin/admin (для разработки!)
superset fab create-admin \
  --username admin \
  --firstname Admin \
  --lastname User \
  --email admin@example.com \
  --password admin || true

echo "=== Superset готов к работе ==="
