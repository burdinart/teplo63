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
from PIL import Image

# ================== НАСТРОЙКИ ==================
TELEGRAM_TOKEN = "7911522105:AAHvBBpGBy_GUx_lXH36q0bwhTp6AiBj1HA"
CHANNEL_ID = -1002132791742
YANDEX_FOLDER_ID = "b1gscpojo096np45ancr"
YANDEX_API_KEY = "AQVNzuMDEixug9ZFoiRvCFbHeEYvNE45_ZS3aVg9"

# ================== НАСТРОЙКА ЛОГИРОВАНИЯ ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================== ИНИЦИАЛИЗАЦИЯ БОТА ==================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ================== ФУНКЦИИ ДЛЯ РАБОТЫ С YANDEXGPT ==================

def call_yandexgpt(prompt: str, model: str = "yandexgpt-lite") -> str:
    """Отправляет запрос к YandexGPT и возвращает текст ответа."""
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
            {"role": "system", "text": "Ты полезный ассистент, который помогает создавать контент для Telegram-канала."},
            {"role": "user", "text": prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Ошибка YandexGPT: {response.status_code} - {response.text}")

        result = response.json()
        try:
            text = result["result"]["alternatives"][0]["message"]["text"]
            return text
        except (KeyError, IndexError) as e:
            raise Exception(f"Неожиданный формат ответа от YandexGPT: {result}")
    except requests.exceptions.Timeout:
        raise Exception("Таймаут при запросе к YandexGPT")
    except Exception as e:
        raise Exception(f"Ошибка при вызове YandexGPT: {e}")

# ================== ФУНКЦИИ ДЛЯ РАБОТЫ С YANDEXART ==================

def generate_image(prompt: str, max_attempts: int = 15, delay: int = 2) -> BytesIO:
    """Генерирует изображение через YandexART по текстовому описанию."""
    logger.info(f"Генерация изображения, промпт: {prompt[:100]}...")
    
    # 1. Запускаем асинхронную генерацию
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
    data = {
        "modelUri": f"art://{YANDEX_FOLDER_ID}/yandex-art/latest",
        "messages": [{"text": prompt}]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Ошибка запуска генерации: {response.text}")
    except requests.exceptions.Timeout:
        raise Exception("Таймаут при запуске генерации изображения")
    except Exception as e:
        raise Exception(f"Ошибка при запросе генерации: {e}")

    try:
        operation_id = response.json()["id"]
        logger.info(f"Запущена генерация изображения, operation_id: {operation_id}")
    except (KeyError, ValueError) as e:
        raise Exception(f"Не удалось получить operation_id из ответа: {response.text[:200]}")

    # 2. Опрашиваем статус операции (исправленный URL)
    status_url = f"https://operation.api.cloud.yandex.net/operations/{operation_id}"
    for attempt in range(max_attempts):
        time.sleep(delay)
        try:
            op_response = requests.get(status_url, headers=headers, timeout=30)
            if op_response.status_code != 200:
                logger.warning(f"Попытка {attempt+1}: не удалось получить статус, код {op_response.status_code}")
                continue
        except requests.exceptions.Timeout:
            logger.warning(f"Попытка {attempt+1}: таймаут при запросе статуса")
            continue
        except Exception as e:
            logger.warning(f"Попытка {attempt+1}: ошибка запроса статуса: {e}")
            continue

        try:
            data = op_response.json()
        except ValueError:
            logger.warning(f"Попытка {attempt+1}: не удалось распарсить ответ статуса")
            continue

        if data.get("done"):
            # Проверяем, нет ли ошибки
            if "error" in data:
                error_msg = data["error"].get("message", "Неизвестная ошибка")
                raise Exception(f"Ошибка при генерации изображения: {error_msg}")

            if "response" in data and "image" in data["response"]:
                image_base64 = data["response"]["image"]
                if image_base64.startswith('data:image'):
                    image_base64 = image_base64.split(',', 1)[1]
                try:
                    image_bytes = base64.b64decode(image_base64)
                    logger.info("Изображение успешно получено и декодировано")
                    return BytesIO(image_bytes)
                except Exception as e:
                    raise Exception(f"Ошибка декодирования base64: {e}")
            else:
                raise Exception("Неожиданный формат ответа от YandexART: отсутствует поле response.image")
    else:
        raise TimeoutError("Превышено время ожидания генерации изображения")

def generate_image_prompt(post_text: str, post_type: str) -> str:
    """Генерирует промпт для картинки на основе текста поста."""
    if post_type == "meme":
        prompt_text = f"Придумай визуально смешную сцену для мема по этому тексту: {post_text}"
    else:
        prompt_text = f"Создай детальное описание для иллюстрации к этому посту: {post_text}"
    try:
        return call_yandexgpt(prompt_text, model="yandexgpt-lite")
    except Exception as e:
        logger.error(f"Ошибка при генерации промпта для картинки: {e}")
        return f"Иллюстрация к посту: {post_text[:200]}"

def get_prompt(post_type: str, topic: str = None) -> str:
    """Возвращает промпт для YandexGPT в зависимости от типа поста."""
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
    """Генерирует и публикует пост (текст + картинка) в канал."""
    if not post_type:
        post_type = random.choice(["advice", "tech_solution", "meme"])

    # 1. Генерация текста
    text_prompt = get_prompt(post_type, topic)
    try:
        text = call_yandexgpt(text_prompt)
        logger.info(f"Текст поста (тип {post_type}) сгенерирован")
    except Exception as e:
        logger.error(f"Ошибка генерации текста: {e}")
        raise Exception("Не удалось сгенерировать текст поста")

    # 2. Генерация промпта для картинки
    image_prompt = generate_image_prompt(text, post_type)
    logger.info(f"Промпт для картинки: {image_prompt[:100]}...")

    # 3. Генерация изображения
    try:
        image_file = generate_image(image_prompt)
        logger.info("Изображение сгенерировано")
    except Exception as e:
        logger.error(f"Не удалось сгенерировать изображение: {e}")
        bot.send_message(CHANNEL_ID, text)
        return

    # ---- СЖАТИЕ ИЗОБРАЖЕНИЯ ----
    try:
        image_file.seek(0)
        # Проверка на пустоту
        first_byte = image_file.read(1)
        if not first_byte:
            raise ValueError("Исходное изображение пустое")
        image_file.seek(0)

        img = Image.open(image_file)
        # Конвертируем RGBA в RGB (для JPEG)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        # Уменьшаем размер, сохраняя пропорции
        img.thumbnail((640,640))
        # Сохраняем в BytesIO с качеством 85%
        compressed = BytesIO()
        img.save(compressed, format='JPEG', quality=50)
        compressed.seek(0)
        if compressed.getbuffer().nbytes == 0:
            raise ValueError("Сжатое изображение пустое")
        image_file = compressed
        logger.info("Изображение успешно сжато")
    except Exception as e:
        logger.error(f"Ошибка при сжатии изображения: {e}")
        bot.send_message(CHANNEL_ID, text)
        return

    # 4. Отправка фото (только один раз!)
    try:
        bot.send_photo(CHANNEL_ID, image_file, caption=text, timeout=60)
        logger.info("Пост опубликован в канале")
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        bot.send_message(CHANNEL_ID, text)

# ================== НОВОСТНЫЕ ФУНКЦИИ ==================

def fetch_plumbing_news(hours=24):
    """Собирает новости из RSS-лент."""
    sources = [
        ("https://www.c-o-k.ru/rss/index.php", "С-О-К (новости)"),
    ]
    news_items = []
    cutoff_time = datetime.now() - timedelta(hours=hours)
    for url, name in sources:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime(*entry.published_parsed[:6])
                    if pub_date < cutoff_time:
                        continue
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
    """Формирует пост из новости через YandexGPT."""
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
    """Публикует свежие новости в канал."""
    logger.info("Начинаю сбор новостей...")
    news = fetch_plumbing_news()
    if not news:
        logger.info("Новых новостей нет")
        return
    for item in news:
        try:
            post_text = generate_news_post(item)
            bot.send_message(CHANNEL_ID, post_text)
            time.sleep(60)
            logger.info(f"Опубликована новость: {item['title'][:50]}...")
        except Exception as e:
            logger.error(f"Ошибка при публикации новости: {e}")

# ================== ПЛАНИРОВЩИК НОВОСТЕЙ ==================

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

schedule.every().day.at("10:00").do(publish_news)
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
    bot.reply_to(message, "🔍 Собираю свежие новости...")
    try:
        publish_news()
        bot.reply_to(message, "✅ Новости опубликованы в канале!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        logger.exception("Ошибка при ручном запуске новостей")

@bot.message_handler(commands=['sources'])
def handle_sources(message):
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
