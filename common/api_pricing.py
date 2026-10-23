"""What an API request costs, in USD, from the token usage the API reports.

The prices are typed in by hand from the pricing page, not fetched, so check them before a long run.
Every budget in this repository (the solver's per-run cap, the updater's cap, the RSI loop's --max-usd)
is counted with these numbers.
"""
from dataclasses import dataclass

# a 5-minute cache write costs this many times the input price, on every model
CACHE_WRITE_MULTIPLIER = 1.25

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def usage_count(usage, field):
    """One token count from an API usage object or from a plain dict (a saved usage); missing means 0."""
    value = usage.get(field) if isinstance(usage, dict) else getattr(usage, field, None)
    return value or 0


def usage_as_dict(usage):
    return {field: usage_count(usage, field) for field in USAGE_FIELDS}


@dataclass(frozen=True)
class ModelPrice:
    model_id: str
    usd_per_million_input_tokens: float
    usd_per_million_output_tokens: float
    cache_read_multiplier: float                    # a cache read costs this fraction of the input price
    long_prompt_threshold_tokens: int | None = None  # past this many prompt tokens...
    long_prompt_multiplier: float = 1.0             # ...the whole request is billed at this multiple

    def rates_for_prompt(self, prompt_tokens):
        """(USD per input token, USD per output token) for a request whose prompt has this many tokens."""
        long_prompt = self.long_prompt_threshold_tokens is not None and prompt_tokens > self.long_prompt_threshold_tokens
        multiplier = self.long_prompt_multiplier if long_prompt else 1.0
        return (self.usd_per_million_input_tokens * multiplier / 1e6,
                self.usd_per_million_output_tokens * multiplier / 1e6)

    def request_cost(self, usage):
        """Cost of one finished request."""
        uncached = usage_count(usage, "input_tokens")
        cache_read = usage_count(usage, "cache_read_input_tokens")
        cache_write = usage_count(usage, "cache_creation_input_tokens")
        input_rate, output_rate = self.rates_for_prompt(uncached + cache_read + cache_write)
        return (uncached * input_rate
                + cache_read * input_rate * self.cache_read_multiplier
                + cache_write * input_rate * CACHE_WRITE_MULTIPLIER
                + usage_count(usage, "output_tokens") * output_rate)

    def worst_case_next_request_cost(self, previous_usage, max_output_tokens, extra_input_tokens):
        """An upper bound on the next request of a conversation: everything so far (plus extra_input_tokens,
        a full tool result counted as one token per character) written to the cache, and a maximum-length answer."""
        context_tokens = (sum(usage_count(previous_usage, field) for field in USAGE_FIELDS) + extra_input_tokens)
        input_rate, output_rate = self.rates_for_prompt(context_tokens)
        return context_tokens * input_rate * CACHE_WRITE_MULTIPLIER + max_output_tokens * output_rate


MODEL_PRICES = {price.model_id: price for price in (
    # Haiku 5.5 bills the whole request at 5x once the prompt passes 100K tokens
    ModelPrice("claude-haiku-5-5", 0.10, 0.50, 0.10, long_prompt_threshold_tokens=100_000, long_prompt_multiplier=5.0),
    ModelPrice("claude-sonnet-5-5", 2.0, 10.0, 0.10),
    ModelPrice("claude-opus-5-5", 4.0, 20.0, 0.05),
)}

# the solver's model and effort can be given by number on the command line, as before
MODEL_IDS_BY_NUMBER = {1: "claude-haiku-5-5", 2: "claude-sonnet-5-5", 3: "claude-opus-5-5"}
MODEL_IDS_BY_SHORT_NAME = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def price_for(model_id):
    if model_id not in MODEL_PRICES:
        raise KeyError(f"no price for {model_id}; add it to common/api_pricing.py (known: {sorted(MODEL_PRICES)})")
    return MODEL_PRICES[model_id]


def resolve_model_id(choice):
    """'1', 'haiku' or 'claude-haiku-5-5' -> 'claude-haiku-5-5'."""
    text = str(choice).strip().lower()
    if text.isdigit() and int(text) in MODEL_IDS_BY_NUMBER:
        return MODEL_IDS_BY_NUMBER[int(text)]
    if text in MODEL_IDS_BY_SHORT_NAME:
        return MODEL_IDS_BY_SHORT_NAME[text]
    if text in MODEL_PRICES:
        return text
    raise ValueError(f"unknown model {choice!r}: use 1-3, haiku, sonnet, opus or a full model id")


def resolve_effort(choice):
    """'1' or 'low' -> 'low'."""
    text = str(choice).strip().lower()
    if text.isdigit() and 1 <= int(text) <= len(EFFORT_LEVELS):
        return EFFORT_LEVELS[int(text) - 1]
    if text in EFFORT_LEVELS:
        return text
    raise ValueError(f"unknown effort {choice!r}: use 1-5 or one of {EFFORT_LEVELS}")
