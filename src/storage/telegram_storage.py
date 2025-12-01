import json
import os
from datetime import datetime

from src.common.logger import logger


class TelegramStorage:
    """Класс для сохранения сообщений, отправленных в Telegram."""

    def __init__(self, storage_path: str = "telegram_messages"):
        self.storage_path = storage_path
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

    def save_message(self, message_text: str, channel_id: str) -> None:
        """Сохраняет текст сообщения в файл."""
        try:
            filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
            filepath = os.path.join(self.storage_path, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "channel_id": channel_id,
                        "timestamp": datetime.now().isoformat(),
                        "message": message_text,
                    },
                    f,
                    ensure_ascii=False,
                    indent=4,
                )
            logger.info(f"Saved Telegram message to {filepath}")
        except IOError as e:
            logger.error(f"Error saving Telegram message: {e}")
