"""
Генератор событий для интернет-магазина одежды.

Создаёт реалистичный поток событий пользовательских действий:
- просмотр каталога / карточки товара
- добавление в корзину / избранное
- оформление заказа

Поддерживает сценарии: нормальная работа, пиковые нагрузки, аномалии.
"""

import json
import time
import random
import os
import math
import logging
from datetime import datetime, timezone

from confluent_kafka import Producer
from faker import Faker

# ---------------------------------------------------------------------------
#  Настройка логирования
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("event-generator")

# ---------------------------------------------------------------------------
#  Конфигурация (берётся из переменных окружения с дефолтами)
# ---------------------------------------------------------------------------
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "raw_events")

# Базовая интенсивность — среднее кол-во событий в секунду
BASE_RATE = float(os.getenv("BASE_RATE", "5"))

# Режим работы: normal / peak / anomaly
SCENARIO = os.getenv("SCENARIO", "normal")

# ---------------------------------------------------------------------------
#  Загрузка базы товаров
# ---------------------------------------------------------------------------
PRODUCTS_DB_PATH = os.path.join(os.path.dirname(__file__), "products_db.json")

with open(PRODUCTS_DB_PATH, "r", encoding="utf-8") as f:
    PRODUCTS_DB = json.load(f)

# Плоский список всех товаров для быстрого доступа
ALL_PRODUCTS = []
CATEGORY_MAP: dict[str, list[dict]] = {}
for cat in PRODUCTS_DB["categories"]:
    CATEGORY_MAP[cat["id"]] = cat["products"]
    for prod in cat["products"]:
        ALL_PRODUCTS.append({**prod, "category_id": cat["id"], "category_name": cat["name"]})

# ---------------------------------------------------------------------------
#  Генератор пользовательских ID (имитация ~500 уникальных посетителей)
# ---------------------------------------------------------------------------
fake = Faker("ru_RU")
USER_POOL = [f"user_{i:04d}" for i in range(1, 501)]

# ---------------------------------------------------------------------------
#  Типы событий и их относительные веса
# ---------------------------------------------------------------------------
EVENT_TYPES = {
    "page_view":        40,   # просмотр страницы
    "product_view":     30,   # просмотр карточки товара
    "add_to_cart":      12,   # добавление в корзину
    "add_to_wishlist":   8,   # добавление в избранное
    "remove_from_cart":  3,   # удаление из корзины
    "checkout":          5,   # оформление заказа
    "search":            2,   # поиск по сайту
}

# Страницы каталога (для page_view)
CATALOG_PAGES = [
    "/catalog",
    "/catalog/outerwear",
    "/catalog/tops",
    "/catalog/bottoms",
    "/catalog/shoes",
    "/catalog/accessories",
    "/sale",
    "/new-arrivals",
    "/brands",
]

# Поисковые запросы
SEARCH_QUERIES = [
    "пуховик", "красное платье", "кроссовки Nike", "джинсы",
    "свитер оверсайз", "ремень", "шапка зимняя", "блузка",
    "шорты", "рубашка в клетку", "кеды белые", "сумка кожаная",
]


def _weighted_choice(options: dict) -> str:
    """Выбирает ключ из словаря {значение: вес} с учётом весов."""
    keys = list(options.keys())
    weights = list(options.values())
    return random.choices(keys, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
#  Реалистичные паттерны
# ---------------------------------------------------------------------------

def _time_of_day_multiplier() -> float:
    """
    Имитирует суточную активность пользователей.
    Пик — в 12:00 и 20:00, минимум — ночью (3:00-6:00).
    """
    hour = datetime.now(timezone.utc).hour
    # Двойная синусоида: утренний пик + вечерний пик
    base = 0.3 + 0.35 * (1 + math.sin(math.pi * (hour - 6) / 12))
    evening_boost = 0.35 * max(0, math.sin(math.pi * (hour - 16) / 8))
    return base + evening_boost


def _scenario_multiplier() -> float:
    """
    Множитель интенсивности в зависимости от сценария.
    - normal:  x1
    - peak:    x3-5 (распродажа / «Чёрная пятница»)
    - anomaly: случайные всплески x0.1-10
    """
    if SCENARIO == "peak":
        return random.uniform(3.0, 5.0)
    if SCENARIO == "anomaly":
        # С вероятностью 10 % — резкий всплеск или провал
        if random.random() < 0.10:
            return random.choice([0.1, 8.0, 10.0])
        return random.uniform(0.5, 2.0)
    return 1.0


def _pick_referrer(event_type: str, product: dict | None) -> str | None:
    """
    Генерирует реалистичный referrer (предыдущую страницу).
    Например, перед product_view часто идёт каталог,
    перед checkout — корзина.
    """
    if event_type == "page_view":
        # 60 % — прямой заход, 40 % — с другой страницы
        if random.random() < 0.4:
            return random.choice(CATALOG_PAGES)
        return None
    if event_type == "product_view":
        # Чаще всего приходят из каталога
        return random.choice(CATALOG_PAGES)
    if event_type in ("add_to_cart", "add_to_wishlist"):
        # Приходят из карточки товара
        return product["url"] if product else None
    if event_type == "checkout":
        return "/cart"
    if event_type == "remove_from_cart":
        return "/cart"
    if event_type == "search":
        return random.choice(["/", "/catalog", None])
    return None


# ---------------------------------------------------------------------------
#  Генерация одного события
# ---------------------------------------------------------------------------

def generate_event() -> dict:
    """Генерирует одно событие с реалистичными полями."""
    event_type = _weighted_choice(EVENT_TYPES)

    # Выбираем случайный товар (если тип события связан с товаром)
    product = None
    if event_type in ("product_view", "add_to_cart", "add_to_wishlist", "remove_from_cart", "checkout"):
        product = random.choice(ALL_PRODUCTS)

    user_id = random.choice(USER_POOL)
    timestamp = datetime.now(timezone.utc).isoformat()

    event = {
        "event_id": fake.uuid4(),
        "event_type": event_type,
        "timestamp": timestamp,
        "user_id": user_id,
    }

    # Поля, зависящие от типа события
    if product:
        event["product_id"] = product["id"]
        event["product_name"] = product["name"]
        event["category_id"] = product["category_id"]
        event["category_name"] = product["category_name"]
        event["brand"] = product["brand"]
        event["price"] = product["price"]
        event["url"] = product["url"]
    elif event_type == "page_view":
        page = random.choice(CATALOG_PAGES)
        event["url"] = page
    elif event_type == "search":
        event["search_query"] = random.choice(SEARCH_QUERIES)
        event["url"] = "/search"

    # Ссылка на предыдущую страницу
    referrer = _pick_referrer(event_type, product)
    if referrer:
        event["referrer"] = referrer

    # Дополнительные метаданные
    event["session_id"] = f"sess_{user_id}_{random.randint(1, 5)}"
    event["device"] = random.choices(
        ["desktop", "mobile", "tablet"],
        weights=[45, 45, 10],
        k=1,
    )[0]

    return event


# ---------------------------------------------------------------------------
#  Kafka Producer
# ---------------------------------------------------------------------------

def delivery_callback(err, msg):
    """Колбэк, вызываемый после доставки сообщения в Kafka."""
    if err:
        logger.error("Ошибка доставки: %s", err)
    else:
        logger.debug(
            "Доставлено: topic=%s partition=%s offset=%s",
            msg.topic(), msg.partition(), msg.offset(),
        )


def create_producer() -> Producer:
    """Создаёт Kafka-продюсер с настройками надёжной доставки."""
    conf = {
        "bootstrap.servers": KAFKA_BROKER,
        # Ожидаем подтверждения от всех in-sync реплик
        "acks": "all",
        # Повторные попытки при временных ошибках
        "retries": 5,
        "retry.backoff.ms": 500,
        # Идемпотентность — защита от дубликатов при retry
        "enable.idempotence": True,
        # Сжатие для уменьшения трафика
        "compression.type": "lz4",
    }
    return Producer(conf)


def wait_for_kafka(producer: Producer, max_retries: int = 30, delay: int = 5):
    """Ожидает готовности Kafka-брокера перед началом генерации."""
    for attempt in range(1, max_retries + 1):
        try:
            # list_topics вызовет исключение, если брокер недоступен
            metadata = producer.list_topics(timeout=5)
            logger.info(
                "Kafka доступна (брокеры: %s). Начинаем генерацию.",
                list(metadata.brokers.values()),
            )
            return
        except Exception:
            logger.warning(
                "Kafka недоступна, попытка %d/%d. Повтор через %d сек...",
                attempt, max_retries, delay,
            )
            time.sleep(delay)
    raise RuntimeError("Не удалось подключиться к Kafka")


# ---------------------------------------------------------------------------
#  Основной цикл генерации
# ---------------------------------------------------------------------------

def main():
    logger.info(
        "Запуск генератора: broker=%s topic=%s rate=%.1f evt/s scenario=%s",
        KAFKA_BROKER, KAFKA_TOPIC, BASE_RATE, SCENARIO,
    )

    producer = create_producer()
    wait_for_kafka(producer)

    events_sent = 0

    try:
        while True:
            # Вычисляем текущую интенсивность с учётом паттернов
            rate = BASE_RATE * _time_of_day_multiplier() * _scenario_multiplier()
            # Интервал между событиями (в секундах)
            interval = 1.0 / max(rate, 0.1)

            event = generate_event()
            payload = json.dumps(event, ensure_ascii=False).encode("utf-8")

            # Отправляем в Kafka; ключ — user_id для партиционирования
            producer.produce(
                topic=KAFKA_TOPIC,
                key=event["user_id"].encode("utf-8"),
                value=payload,
                callback=delivery_callback,
            )

            # Периодически вызываем poll для обработки колбэков
            producer.poll(0)

            events_sent += 1
            if events_sent % 100 == 0:
                logger.info("Отправлено событий: %d (текущий rate: %.1f evt/s)", events_sent, rate)

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Остановка генератора. Всего отправлено: %d", events_sent)
    finally:
        # Дожидаемся отправки всех сообщений из буфера
        producer.flush(timeout=10)


if __name__ == "__main__":
    main()
