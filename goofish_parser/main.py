import logging
import sys
from pathlib import Path

_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from goofish_parser.bot.bot import run_bot
from goofish_parser.storage.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Initializing database...")
    init_db()

    logger.info("Starting Telegram bot...")
    run_bot()


if __name__ == "__main__":
    main()
