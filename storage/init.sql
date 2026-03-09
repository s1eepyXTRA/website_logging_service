-- ============================================================
-- Инициализация ClickHouse: создание схем и таблиц
--
-- Архитектура:
--   dwh (Data Warehouse) — слой сырых данных
--   marts                — слой витрин (агрегированных данных)
-- ============================================================

-- ==============================
-- 1. Схема DWH — сырые данные
-- ==============================
CREATE DATABASE IF NOT EXISTS dwh;

-- Таблица сырых событий.
-- Движок MergeTree — основной движок ClickHouse для аналитики.
-- Данные партиционируются по дням для быстрого удаления старых данных.
-- Сортировка по (event_type, user_id, timestamp) ускоряет типовые запросы.
CREATE TABLE IF NOT EXISTS dwh.raw_events
(
    event_id      String,
    event_type    LowCardinality(String),  -- мало уникальных значений → экономия памяти
    timestamp     DateTime64(3),           -- миллисекундная точность
    user_id       String,
    session_id    String,
    product_id    Nullable(String),
    product_name  Nullable(String),
    category_id   Nullable(String),
    category_name Nullable(String),
    brand         Nullable(String),
    price         Nullable(Float64),
    url           Nullable(String),
    referrer      Nullable(String),
    search_query  Nullable(String),
    device        LowCardinality(String),
    processed_at  DateTime64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (event_type, user_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 90 DAY  -- автоудаление через 90 дней
SETTINGS index_granularity = 8192;


-- ==============================
-- 2. Схема MARTS — витрины данных
-- ==============================
CREATE DATABASE IF NOT EXISTS marts;

-- Витрина: ежедневная статистика по типам событий.
-- Используем SummingMergeTree — он автоматически суммирует
-- числовые колонки при слиянии частей (оптимизация для счётчиков).
CREATE TABLE IF NOT EXISTS marts.daily_events_summary
(
    event_date    Date,
    event_type    LowCardinality(String),
    device        LowCardinality(String),
    event_count   UInt64,
    unique_users  AggregateFunction(uniq, String)
)
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, event_type, device);

-- Материализованное представление: автоматически агрегирует данные
-- из dwh.raw_events в витрину marts.daily_events_summary
-- при каждой вставке новых данных.
CREATE MATERIALIZED VIEW IF NOT EXISTS marts.daily_events_summary_mv
TO marts.daily_events_summary
AS
SELECT
    toDate(timestamp) AS event_date,
    event_type,
    device,
    count() AS event_count,
    uniqState(user_id) AS unique_users
FROM dwh.raw_events
GROUP BY event_date, event_type, device;


-- Витрина: статистика по категориям товаров.
CREATE TABLE IF NOT EXISTS marts.category_stats
(
    event_date     Date,
    category_id    String,
    category_name  String,
    views_count    UInt64,
    cart_adds      UInt64,
    purchases      UInt64,
    total_revenue  Float64
)
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, category_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS marts.category_stats_mv
TO marts.category_stats
AS
SELECT
    toDate(timestamp) AS event_date,
    category_id,
    any(category_name) AS category_name,
    countIf(event_type = 'product_view') AS views_count,
    countIf(event_type = 'add_to_cart') AS cart_adds,
    countIf(event_type = 'checkout') AS purchases,
    sumIf(coalesce(price, 0), event_type = 'checkout') AS total_revenue
FROM dwh.raw_events
WHERE category_id IS NOT NULL
GROUP BY event_date, category_id;


-- Витрина: статистика по брендам.
CREATE TABLE IF NOT EXISTS marts.brand_stats
(
    event_date   Date,
    brand        String,
    views_count  UInt64,
    cart_adds    UInt64,
    purchases    UInt64,
    total_revenue Float64
)
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, brand);

CREATE MATERIALIZED VIEW IF NOT EXISTS marts.brand_stats_mv
TO marts.brand_stats
AS
SELECT
    toDate(timestamp) AS event_date,
    brand,
    countIf(event_type = 'product_view') AS views_count,
    countIf(event_type = 'add_to_cart') AS cart_adds,
    countIf(event_type = 'checkout') AS purchases,
    sumIf(coalesce(price, 0), event_type = 'checkout') AS total_revenue
FROM dwh.raw_events
WHERE brand IS NOT NULL
GROUP BY event_date, brand;


-- Витрина: воронка конверсий (по часам).
CREATE TABLE IF NOT EXISTS marts.conversion_funnel
(
    event_hour     DateTime,
    page_views     UInt64,
    product_views  UInt64,
    add_to_cart    UInt64,
    checkouts      UInt64
)
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMMDD(event_hour)
ORDER BY (event_hour);

CREATE MATERIALIZED VIEW IF NOT EXISTS marts.conversion_funnel_mv
TO marts.conversion_funnel
AS
SELECT
    toStartOfHour(timestamp) AS event_hour,
    countIf(event_type = 'page_view') AS page_views,
    countIf(event_type = 'product_view') AS product_views,
    countIf(event_type = 'add_to_cart') AS add_to_cart,
    countIf(event_type = 'checkout') AS checkouts
FROM dwh.raw_events
GROUP BY event_hour;
