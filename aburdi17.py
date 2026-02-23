import os
import base64
import random
import time
import logging
import threading
import feedparser
import schedule
from io import BytesIO
from datetime import datetime, timedelta

import requests
import telebot

# ================== НАСТРОЙКИ ==================
# Вставьте сюда свои данные (или используйте переменные окружения)
TELEGRAM_TOKEN = "7911522105:AAHvBBpGBy_GUx_lXH36q0bwhTp6AiBj1HA"          # Токен от @BotFather
CHANNEL_ID = -1002132791742                     # Например @moy_kanal или числовой ID
YANDEX_FOLDER_ID = "b1gu06g1kaii6vhtjgk3"                   # ID каталога в Yandex Cloud
YANDEX_API_KEY = "AQVNw3FyOHS7XEnPF8m2DxOEtPcvNC_-C3qmUwMG"                   # 


# ================== НАСТРОЙКА ЛОГИРОВАНИЯ ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================== ИНИЦИАЛИЗАЦИЯ ==================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ================== ФУНКЦИИ ДЛЯ РАБОТЫ С YANDEXGPT ==================

def call_yandexgpt(prompt: str, model: str = "yandexgpt-lite") -> str:
    """
    Отправляет запрос к YandexGPT через REST API и возвращает текст ответа.
    """
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{model}",
        "completionOptions": {
            "stream": False,
            "temperature": 0.6,
            "maxTokens": "2000"
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты полезный ассистент, который помогает создавать контент для Telegram-канала."
            },
            {
                "role": "user",
                "text": prompt
            }
        ]
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        raise Exception(f"Ошибка YandexGPT: {response.status_code} - {response.text}")

    result = response.json()
    try:
        text = result["result"]["alternatives"][0]["message"]["text"]
        return text
    except (KeyError, IndexError) as e:
        raise Exception(f"Неожиданный формат ответа от YandexGPT: {result}")

# ================== ФУНКЦИИ ДЛЯ РАБОТЫ С YANDEXART ==================

def generate_image(prompt: str, max_attempts: int = 30, delay: int = 5) -> BytesIO:
    """
    Генерирует изображение через YandexART по текстовому описанию.
    Возвращает файлоподобный объект BytesIO с изображением.
    """
    # 1. Запускаем асинхронную генерацию
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
    data = {
        "modelUri": f"art://{YANDEX_FOLDER_ID}/yandex-art/latest",
        "messages": [{"text": prompt}]
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        raise Exception(f"Ошибка запуска генерации: {response.text}")

    operation_id = response.json()["id"]
    logger.info(f"Запущена генерация изображения, operation_id: {operation_id}")

    # 2. Опрашиваем статус операции
    status_url = f"https://llm.api.cloud.yandex.net/operations/{operation_id}"
    for attempt in range(max_attempts):
        time.sleep(delay)
        op_response = requests.get(status_url, headers=headers)
        if op_response.status_code != 200:
            logger.warning(f"Попытка {attempt+1}: не удалось получить статус, код {op_response.status_code}")
            continue

        data = op_response.json()
        if data.get("done"):
            # Изображение готово — извлекаем base64
            if "response" in data and "image" in data["response"]:
                image_base64 = data["response"]["image"]
                # Убираем возможный префикс data:image/png;base64,
                if image_base64.startswith('data:image'):
                    image_base64 = image_base64.split(',', 1)[1]
                image_bytes = base64.b64decode(image_base64)
                logger.info("Изображение успешно получено и декодировано")
                return BytesIO(image_bytes)
            else:
                raise Exception("Неожиданный формат ответа от YandexART: отсутствует поле response.image")
    else:
        raise TimeoutError("Превышено время ожидания генерации изображения")


def generate_image_prompt(post_text: str, post_type: str) -> str:
    """
    На основе текста поста генерирует промпт для YandexART.
    При ошибке возвращает упрощённый промпт.
    """
    if post_type == "meme":
        prompt_text = f"Придумай визуально смешную сцену для мема по этому тексту: {post_text}"
    else:
        prompt_text = f"Создай детальное описание для иллюстрации к этому посту: {post_text}"

    try:
        return call_yandexgpt(prompt_text, model="yandexgpt-lite")
    except Exception as e:
        logger.error(f"Ошибка при генерации промпта для картинки: {e}")
        # Возвращаем упрощённый промпт на основе текста поста
        return f"Иллюстрация к посту: {post_text[:200]}"


def get_prompt(post_type: str, topic: str = None) -> str:
    """
    Возвращает промпт для YandexGPT в зависимости от типа поста и темы.
    """
    templates = {
        "advice": (
            "Ты — опытный сантехник и строитель. Напиши полезный совет для домашних мастеров. "
            "Тема: {topic}. Объясни просто, добавь эмодзи и хештеги."
        ),
        "tech_solution": (
            "Ты — инженер-строитель. Опиши интересное техническое решение в сантехнике или строительстве. "
            "Расскажи, как оно работает и где пригодится. Тема: {topic}. Используй эмодзи и хештеги."
        ),
        "meme": (
            "Ты — автор юмористического канала о сантехнике и строительстве. "
            "Придумай смешной мем (шутку) на тему {topic}. Напиши пост с юмором, можно использовать эмодзи и хештеги."
        )
    }
    base = templates.get(
        post_type,
        "Ты — эксперт по сантехнике и строительству. Напиши пост на тему: {topic}. Добавь эмодзи и хештеги."
    )
    topic_str = topic if topic else "сантехника и строительство"
    return base.format(topic=topic_str)


def create_and_publish_post(post_type: str = None, topic: str = None):
    """
    Генерирует пост (текст + картинку) и публикует в Telegram-канал.
    """
    if not post_type:
        post_type = random.choice(["advice", "tech_solution", "meme"])

    # 1. Генерируем текст поста через YandexGPT
    text_prompt = get_prompt(post_type, topic)
    try:
        text = call_yandexgpt(text_prompt)
        logger.info(f"Текст поста (тип {post_type}) сгенерирован")
    except Exception as e:
        logger.error(f"Ошибка генерации текста: {e}")
        raise Exception("Не удалось сгенерировать текст поста")

    # 2. Генерируем промпт для картинки
    image_prompt = generate_image_prompt(text, post_type)
    logger.info(f"Промпт для картинки: {image_prompt[:100]}...")

    # 3. Генерируем изображение через YandexART
    try:
        image_file = generate_image(image_prompt)
        logger.info("Изображение сгенерировано")
    except Exception as e:
        logger.error(f"Не удалось сгенерировать изображение: {e}")
        # Если картинка не создалась, отправляем только текст
        bot.send_message(CHANNEL_ID, text)
        return

    # 4. Отправляем в Telegram (фото + подпись)
    try:
        bot.send_photo(CHANNEL_ID, image_file, caption=text)
        logger.info("Пост опубликован в канале")
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        bot.send_message(CHANNEL_ID, text)


# ================== НОВОСТНЫЕ ФУНКЦИИ ==================

def fetch_plumbing_news(hours=24):
    """
    Собирает новости из RSS-лент за последние hours часов.
    Возвращает список словарей с заголовком, текстом, ссылкой и источником.
    """
    sources = [
        # Русскоязычные источники
        ("https://www.c-o-k.ru/rss/index.php", "С-О-К (новости)"),
       
    ]
    
    news_items = []
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    for url, name in sources:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                # Проверяем дату публикации (если есть)
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime(*entry.published_parsed[:6])
                    if pub_date < cutoff_time:
                        continue
                
                # Добавляем новость, даже если нет ключевых слов (но проверяем, что есть заголовок)
                if entry.title and entry.title.strip():
                    news_items.append({
                        'title': entry.title,
                        'summary': entry.summary if hasattr(entry, 'summary') else '',
                        'link': entry.link,
                        'source': name
                    })
        except Exception as e:
            logger.error(f"Ошибка при парсинге {name}: {e}")
    
    return news_items


def generate_news_post(news_item):
    """
    Превращает сырую новость в пост для Telegram через YandexGPT.
    """
    prompt = f"""
    Ты — редактор Telegram-канала о сантехнике и строительстве.
    Перепиши эту новость в формате поста для канала:
    
    Заголовок: {news_item['title']}
    Текст: {news_item['summary']}
    Ссылка на источник: {news_item['link']}
    
    Требования к посту:
    - Сделай кратко (3-5 предложений)
    - Добавь эмодзи
    - В конце добавь хештеги: #новости #сантехника #строительство
    - Обязательно укажи ссылку на источник в формате "Подробнее: [ссылка]"
    """
    
    return call_yandexgpt(prompt)


def publish_news():
    """Собирает свежие новости и публикует их в канал."""
    logger.info("Начинаю сбор новостей...")
    news = fetch_plumbing_news()
    if not news:
        logger.info("Новых новостей нет")
        return
    
    for item in news:
        try:
            post_text = generate_news_post(item)
            bot.send_message(CHANNEL_ID, post_text)
            time.sleep(60)  # пауза между постами, чтобы не зафлудить
            logger.info(f"Опубликована новость: {item['title'][:50]}...")
        except Exception as e:
            logger.error(f"Ошибка при публикации новости: {e}")


# ================== ПЛАНИРОВЩИК НОВОСТЕЙ ==================

def run_schedule():
    """Запускает планировщик в бесконечном цикле."""
    while True:
        schedule.run_pending()
        time.sleep(60)

# Настраиваем расписание: каждый день в 10:00
schedule.every().day.at("10:00").do(publish_news)

# Запускаем планировщик в фоновом потоке
scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
scheduler_thread.start()
logger.info("Планировщик новостей запущен (ежедневно в 10:00)")


# ================== ОБРАБОТЧИКИ КОМАНД ==================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👋 Привет! Я бот для создания постов о сантехнике и строительстве.\n\n"
        "<b>Основные команды:</b>\n"
        "/post [тип] [тема] — сгенерировать и опубликовать пост.\n"
        "   Тип: advice (совет), tech_solution (решение), meme (мем).\n"
        "   Если тип не указан, выбирается случайно.\n"
        "   Тема — любая фраза (например, \"засор в трубе\").\n\n"
        "<b>Новостные команды:</b>\n"
        "/news — принудительно собрать и опубликовать свежие новости\n"
        "/sources — показать список источников новостей\n\n"
        "Примеры:\n"
        "/post advice протечка\n"
        "/post meme инструменты\n"
        "/news"
    )
    bot.reply_to(message, welcome_text, parse_mode="HTML")

@bot.message_handler(commands=['post'])
def handle_post(message):
    parts = message.text.split(maxsplit=2)
    post_type = None
    topic = None

    if len(parts) >= 2:
        if parts[1] in ["advice", "tech_solution", "meme"]:
            post_type = parts[1]
            if len(parts) == 3:
                topic = parts[2]
        else:
            topic = parts[1]

    bot.reply_to(message, "⏳ Генерирую пост, это может занять до минуты...")

    try:
        create_and_publish_post(post_type, topic)
        bot.send_message(message.chat.id, "✅ Пост опубликован в канале!")
    except Exception as e:
        logger.exception("Ошибка при обработке команды /post")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['news'])
def handle_news(message):
    """Ручной запуск сбора и публикации новостей."""
    bot.reply_to(message, "🔍 Собираю свежие новости...")
    try:
        publish_news()
        bot.reply_to(message, "✅ Новости опубликованы в канале!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        logger.exception("Ошибка при ручном запуске новостей")


@bot.message_handler(commands=['sources'])
def handle_sources(message):
    """Показывает актуальный список источников новостей."""
    sources_text = (
        "📰 **Источники новостей:**\n"
        "- Строй-Лайф (новости, технологии)\n"
        "- Strol (новости, статьи, технологии)\n"
        "- SupplyHT (сантехника, отопление)\n"
        "- PM Magazine (сантехника)\n\n"
        "Хотите добавить свой источник? Сообщите автору бота."
    )
    bot.reply_to(message, sources_text, parse_mode="Markdown")


# ================== ЗАПУСК БОТА ==================
if __name__ == "__main__":
    logger.info("Бот запущен и готов к работе")
    bot.infinity_polling()
