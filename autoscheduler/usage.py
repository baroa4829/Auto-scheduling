"""Claude API 토큰 사용량 기록과 비용 추정."""
from __future__ import annotations

from dataclasses import dataclass

# 모델별 1M 토큰당 USD 가격: (입력, 출력, 캐시 읽기)
# 출처: Anthropic 가격표 (2026-11 기준). 바뀔 수 있으니 https://www.anthropic.com/pricing 확인
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
}
CACHE_WRITE_MULTIPLIER = 1.25  # 캐시 쓰기 = 입력 단가 × 1.25 (5분 캐시)


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def cost_usd(self) -> float | None:
        """가격표에 없는 모델이면 None."""
        price = PRICES.get(self.model)
        if price is None:
            return None
        inp, out, cache_read = price
        return (
            self.input_tokens * inp
            + self.output_tokens * out
            + self.cache_read_tokens * cache_read
            + self.cache_write_tokens * inp * CACHE_WRITE_MULTIPLIER
        ) / 1_000_000

    def describe(self) -> str:
        cost = self.cost_usd
        cost_s = f"≈ ${cost:.4f}" if cost is not None else "(가격표 없음)"
        cache = ""
        if self.cache_read_tokens or self.cache_write_tokens:
            cache = f" / 캐시 읽기 {self.cache_read_tokens:,} / 캐시 쓰기 {self.cache_write_tokens:,}"
        return (f"{self.model}: 호출 {self.calls}회, 입력 {self.input_tokens:,} / "
                f"출력 {self.output_tokens:,}{cache} 토큰 {cost_s}")


def from_response(response) -> Usage:
    u = response.usage
    return Usage(
        model=getattr(response, "model", "") or "",
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        calls=1,
    )
