# Джарвис

Локальный ассистент для Windows, который собирает список дел из рабочей переписки в Telegram. Переписка обрабатывается на вашем компьютере и никуда не отправляется.

Статус: MVP в разработке, срок — конец ноября 2026. Что входит в MVP, архитектура и правила разработки — в [CLAUDE.md](CLAUDE.md).

## Установка для разработки

```powershell
git clone https://github.com/Ynuty/Jarvis-main.git
cd Jarvis-main
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[telegram,secure,dev]"
pytest
```

## Тестовый режим: импорт экспорта чатов

1. В Telegram Desktop: **Настройки → Продвинутые настройки → Экспорт данных Telegram** (или в меню нужного чата **Экспорт истории чата**). Формат — **Машиночитаемый JSON**, медиа можно не выгружать.
2. Посмотрите, какие чаты есть в файле:
   ```powershell
   jarvis export-chats путь\к\result.json
   ```
3. Найдите задачи в выбранных чатах. `--me` — как вы подписаны в Telegram (нужно для экспорта одного чата):
   ```powershell
   jarvis import путь\к\result.json --chat "Название чата" --me "Ваше имя"
   ```
4. Работа со списком:
   ```powershell
   jarvis tasks          # открытые задачи
   jarvis done 3         # отметить сделанной
   jarvis dismiss 4      # убрать из списка
   jarvis log            # журнал действий ассистента
   ```

Без модели задачи ищутся правилами. Для точного разбора поставьте [Ollama](https://ollama.com), скачайте модель (`ollama pull qwen2.5:7b-instruct`) и добавьте к команде `--model qwen2.5:7b-instruct`.

Экспорты переписки не кладите в папку репозитория — `.gitignore` их отсекает, но лучше держать их отдельно.

## Живое подключение (только чтение)

```powershell
jarvis live setup     # api_id и api_hash с https://my.telegram.org → API development tools
jarvis live login     # вход по номеру, код придёт в Telegram
jarvis live chats
jarvis live sync --chat "Название чата"
jarvis live logout    # завершить сессию и удалить её с компьютера
```

Джарвис ничего не отправляет и не отмечает сообщения прочитанными: такие запросы блокируются в коде. Сессия хранится в Диспетчере учётных данных Windows.

## Команда

Миша (Ynuty), Егор (dor1tozz), Рома (clipsmatrix).
