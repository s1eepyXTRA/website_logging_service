# ============================================================
# Конфигурация Apache Superset
#
# Superset — инструмент визуализации данных.
# Здесь указываем подключение к БД метаданных и настройки.
# ============================================================

import os

# Секретный ключ для шифрования сессий (в проде используйте надёжный!)
SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "supersecret_key_change_in_production")

# Подключение к PostgreSQL для хранения метаданных Superset
# (дашборды, датасеты, пользователи и т.д.)
SQLALCHEMY_DATABASE_URI = "postgresql://superset:superset@superset_db:5432/superset"

# Отключаем предупреждение о дефолтном SECRET_KEY
SUPERSET_WEBSERVER_PORT = 8088

# Разрешаем загрузку CSV
CSV_EXTENSIONS = {"csv", "tsv"}

# Язык по умолчанию
BABEL_DEFAULT_LOCALE = "ru"

# Включаем нужные feature flags
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}

# Кэш (простой — для разработки)
CACHE_CONFIG = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
}
