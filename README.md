# Website Analytics Pipeline

Система генерации, хранения и мониторинга для интернет-магазина одежды. Генерирует поток пользовательских событий, собирает и обрабатывает их через Kafka и Vector, хранит в ClickHouse и визуализирует через Grafana и Apache Superset.

# ToDo

Добавить Apache Airflow для возможности создания ETL-пайплайнов DWH -> Data Marts

## Архитектура

### Общая схема

```mermaid
flowchart LR
    Generator["Generator<br/>(Python)"] -->|events| Kafka["Kafka<br/>(KRaft)"]
    Kafka -->|raw_events| Vector
    Vector -->|HTTP insert| ClickHouse
    Vector -->|metrics :9598| Prometheus
    Prometheus --> Grafana["Grafana<br/>(мониторинг)"]
    ClickHouse --> Superset["Superset<br/>(BI-дашборды)"]
```

### Поток данных

```mermaid
flowchart TD
    subgraph Генерация
        G[Generator] -->|JSON events| K[Kafka topic: raw_events<br/>3 партиции]
    end

    subgraph ETL
        K --> V[Vector]
        V -->|валидация| V1{Событие валидно?}
        V1 -->|да| V2[Обогащение<br/>processed_at, defaults]
        V1 -->|нет| DROP[Drop]
        V2 --> CH_SINK[ClickHouse sink<br/>batch 1MB / 5s]
        V2 --> PROM_SINK[Prometheus exporter<br/>:9598]
    end

    subgraph Хранилище
        CH_SINK --> RAW[dwh.raw_events<br/>TTL 90 дней]
        RAW --> MV1[marts.daily_events_summary]
        RAW --> MV2[marts.category_stats]
        RAW --> MV3[marts.brand_stats]
        RAW --> MV4[marts.conversion_funnel]
    end

    subgraph Визуализация
        PROM_SINK --> PROM[Prometheus]
        PROM --> GRAF[Grafana]
        RAW --> SUP[Superset]
        MV1 --> SUP
        MV2 --> SUP
        MV3 --> SUP
        MV4 --> SUP
    end
```

### Инфраструктура (Docker Compose)

```mermaid
flowchart TB
    subgraph Docker Compose
        direction TB
        KAFKA[Kafka :9094] --- VECTOR[Vector :9598]
        VECTOR --- CLICKHOUSE[ClickHouse :8123]
        GENERATOR[Generator] -.->|depends_on| KAFKA
        VECTOR -.->|depends_on| KAFKA
        VECTOR -.->|depends_on| CLICKHOUSE
        PROMETHEUS[Prometheus :9090] -.->|scrapes| VECTOR
        GRAFANA[Grafana :3000] -.->|datasource| PROMETHEUS
        GRAFANA -.->|datasource| CLICKHOUSE
        PG[PostgreSQL] --- SUPERSET[Superset :8088]
        SUPERSET -.->|datasource| CLICKHOUSE
    end
```

### Компоненты

| Сервис | Технология | Назначение |
|--------|-----------|------------|
| **Generator** | Python 3.12, confluent-kafka, faker | Генерация реалистичного потока событий (~500 пользователей) |
| **Kafka** | Apache Kafka 3.7 (KRaft) | Очередь сообщений (топик `raw_events`, 3 партиции) |
| **Vector** | Vector 0.41.1 | ETL-пайплайн: валидация, обогащение, маршрутизация |
| **ClickHouse** | ClickHouse 24.3 | Колоночная OLAP-база для аналитики |
| **Prometheus** | Prometheus 2.51.0 | Сбор метрик пайплайна |
| **Grafana** | Grafana 11.0.0 | Мониторинг (дашборд Vector Pipeline) |
| **Superset** | Apache Superset 3.1.1 | BI-дашборды и ad-hoc аналитика |
| **PostgreSQL** | PostgreSQL 16 | Метаданные Superset |

## Структура проекта

```
website_service/
├── docker-compose.yml        # Докер компос
├── .env.example              # Шаблон переменных окружения
│
├── generator/                # Генератор событий
│   ├── Dockerfile
│   ├── generator.py          # Основной скрипт генерации
│   ├── products_db.json      # База товаров (25 позиций, 5 категорий)
│   └── requirements.txt
│
├── vector/                   # Конфигурация Vector
│   └── vector.yaml
│
├── storage/                  # Схема хранилища Clickhouse
│   └── init.sql              # DDL: raw-слой + аналитические витрины
│
├── prometheus/               # Конфиг Prometheus
│   └── prometheus.yml
│
├── grafana/                  # Grafana  
│   ├── provisioning/
│   │   └── datasources/
│   │       └── datasources.yml
│   └── dashboards/
│       └── vector-pipeline.json
│
└── superset/                 # Конфиг Superset 
    ├── superset_config.py
    └── superset-init.sh
```

## Быстрый старт

### Требования

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

### Запуск

1. **Клонировать репозиторий:**

```bash
git clone <url-репозитория>
cd website_service
```

2. **Создать файл `.env`:**

```bash
cp .env.example .env
```

3. **Запустить все сервисы:**

```bash
docker compose up -d
```

### Доступ к интерфейсам

| Интерфейс | URL | Логин / Пароль |
|-----------|-----|----------------|
| Grafana | http://localhost:3000 | admin / admin |
| Superset | http://localhost:8088 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| ClickHouse (HTTP) | http://localhost:8123 | — |

### Подключение к Superset

В Settings -> Database Connections добавить новое подключение с типом Other (Другое) и вставить, к примеру clickhousedb://default@clickhouse:8123/dwh

## Конфигурация

### Сценарии генерации

Задается переменной `SCENARIO` в `.env`:

| Сценарий | Описание |
|----------|----------|
| `normal` | Обычный трафик с дневными пиками (12:00, 20:00) |
| `peak` | Распродажа — повышенная нагрузка |
| `anomaly` | Аномальные паттерны |

### Типы событий

| Событие | Вес | Описание |
|---------|-----|----------|
| `page_view` | 40% | Просмотр страницы |
| `product_view` | 30% | Просмотр товара |
| `add_to_cart` | 12% | Добавление в корзину |
| `add_to_wishlist` | 8% | Добавление в избранное |
| `checkout` | 5% | Оформление заказа |
| `remove_from_cart` | 3% | Удаление из корзины |
| `search` | 2% | Поиск по каталогу |

## Хранилище данных

### Слой сырых данных (`dwh`)

Таблица `dwh.raw_events` — все входящие события с TTL 90 дней и партиционированием по дате.

### Аналитические витрины (`marts`)

Реализованы как **материализованные представления**, обновляются автоматически. По факту как таковыми витринами не являются, потому что витрины были бы копиями таблицы из DWH, поэтому реализовал как заранее посчитанные метрики:

| Витрина | Описание |
|---------|----------|
| `marts.daily_events_summary` | Почасовая агрегация событий по типу и устройству |
| `marts.category_stats` | Дневная статистика по категориям товаров |
| `marts.brand_stats` | Дневная статистика по брендам |
| `marts.conversion_funnel` | Почасовая воронка конверсии |

## Мониторинг

### Grafana

Предустановленный дашборд **Vector Pipeline Monitoring** отслеживает:
- Скорость приема/отправки событий
- Ошибки обработки
- Consumer lag Kafka

### Prometheus

Метрики Vector доступны на порту `9598`. Prometheus скрейпит их с интервалом 15 секунд.

## Управление

```bash
# Добавление второго генератора при необходимости
docker compose up -d --scale generator=2
```

## Порты

| Порт | Сервис |
|------|--------|
| 3000 | Grafana |
| 8088 | Superset |
| 8123 | ClickHouse HTTP |
| 9090 | Prometheus |
| 9094 | Kafka (внешний доступ) |
| 9598 | Vector (метрики) |

## Безопасность

> Проект настроен для локальной разработки
