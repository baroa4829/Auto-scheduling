from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv(path: Path = Path(".env")) -> None:
    """의존성 없이 .env 파일을 읽어 환경변수로 넣는다 (이미 설정된 값은 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    timezone: str = "Asia/Seoul"
    calendar_id: str = "primary"
    webhook_token: str = ""
    include_tentative: bool = False
    dry_run: bool = False
    data_dir: Path = Path("data")
    model: str = "claude-opus-5-5"
    # 알림 한 건이 올 때 함께 보여줄 같은 채팅방의 직전 메시지 수
    context_messages: int = 30
    context_hours: int = 48
    credentials_file: Path = field(default_factory=lambda: Path("credentials.json"))
    token_file: Path = field(default_factory=lambda: Path("token.json"))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "autoscheduler.db"

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        env = os.environ.get
        return cls(
            timezone=env("AUTOSCHEDULER_TIMEZONE", "Asia/Seoul"),
            calendar_id=env("AUTOSCHEDULER_CALENDAR_ID", "primary"),
            webhook_token=env("AUTOSCHEDULER_WEBHOOK_TOKEN", ""),
            include_tentative=_bool("AUTOSCHEDULER_INCLUDE_TENTATIVE", False),
            dry_run=_bool("AUTOSCHEDULER_DRY_RUN", False),
            data_dir=Path(env("AUTOSCHEDULER_DATA_DIR", "data")),
            model=env("AUTOSCHEDULER_MODEL", "claude-opus-5-5"),
            context_messages=int(env("AUTOSCHEDULER_CONTEXT_MESSAGES", "30")),
            context_hours=int(env("AUTOSCHEDULER_CONTEXT_HOURS", "48")),
            credentials_file=Path(env("GOOGLE_CREDENTIALS_FILE", "credentials.json")),
            token_file=Path(env("GOOGLE_TOKEN_FILE", "token.json")),
        )
