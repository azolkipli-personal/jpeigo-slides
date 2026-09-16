"""Single source of truth for the models the app offers.

Both lists were measured against this app's own traffic, not copied from a
provider's model list — neither provider exposes modality metadata, and a model
being advertised says nothing about whether it accepts *our* payload.

- `TRANSLATE_MODELS` was probed through `translators/service.py`'s real classes on
  a real Japanese sentence, so the temperature and the OpenCode session header
  matched production. Models that reject that payload are absent on purpose:
  `grok-4.6` answers 401 on this plan, `gpt-5.6-luna` answers 500, and
  `kimi-k2.7-code` rejects any temperature but 1 with HTTP 400 "invalid
  temperature". That last one is a payload clash, not a blind model: probed
  directly it names all five blocks at temperature=1, and it is ~3.6x cheaper
  per deck than `kimi-k3` on a $60 cap instead of $15. It is absent from both
  lists only because the client cannot yet send a temperature it accepts — add
  it once that is fixed and its layout review has been measured on a real deck.
- `VISION_MODELS` were each sent an image of five flat colour blocks, which only a
  model that actually receives the pixels can name. The two models already in the
  app, `deepseek-v4-flash` and `minimax-m2.5`, **failed** that test with HTTP 400
  for image content — which is why the slide check needs its own list instead of
  reusing the translation picker.

`GET /api/models` serves this, and `tests/test_model_catalog.py` fails when these
lists drift apart from the translator registry, so the dropdown cannot offer a key
the backend does not know.
"""
from typing import NamedTuple


class Model(NamedTuple):
    """One selectable model.

    `key` is what the UI sends for translations (the registry's key).
    `model` is the provider's actual model ID, shown under the label so a support
    question ("which model produced this?") has an exact answer.
    """

    key: str
    label: str
    lane: str
    model: str
    note: str = ''

    def as_dict(self) -> dict:
        return {'key': self.key, 'label': self.label, 'lane': self.lane,
                'model': self.model, 'note': self.note}


class VisionModel(NamedTuple):
    """One model that can be asked to look at a rendered slide.

    No registry key: the slide check passes the provider model ID straight to
    `qa/client.py`, which routes by lane.
    """

    model: str
    label: str
    note: str = ''

    def as_dict(self) -> dict:
        return {'key': self.model, 'label': self.label, 'lane': 'opencode',
                'model': self.model, 'note': self.note}


# Translation picker. Ordered cheapest-first so the recommended entry leads. The
# OpenCode entries carry their real per-1M-token price, because that plan's limit
# is a dollar amount per model — nothing here is flat-rate.
TRANSLATE_MODELS: tuple[Model, ...] = (
    Model('gemini-25-flash-lite', 'Gemini 2.5 Flash Lite', 'gemini',
          'gemini-2.5-flash-lite',
          'Recommended: the old workhorse, still the failover target'),
    Model('gemini-flash-lite', 'Gemini 3.1 Flash Lite', 'gemini',
          'gemini-3.1-flash-lite', 'Cheap, current, slightly more literal'),
    Model('gemini-flash', 'Gemini 3.5 Flash', 'gemini', 'gemini-3.5-flash',
          'Balanced default; also used by the translation review pass'),
    Model('gemini-flash-38', 'Gemini 3.8 Flash', 'gemini', 'gemini-3.8-flash',
          'Newest flash; natural English on marketing Japanese'),
    Model('gemini-pro', 'Gemini 3.1 Pro', 'gemini', 'gemini-3.1-pro-preview',
          'Slowest and dearest; best on dense technical prose'),
    Model('opencode-deepseek', 'DeepSeek V4.1 Flash', 'opencode',
          'deepseek-v4.1-flash', 'OpenCode, billed per token; sees slides'),
    Model('opencode-kimi', 'Kimi K3', 'opencode', 'kimi-k3',
          'OpenCode; dearest here at $3/$15 per M on a $15 monthly cap'),
    Model('opencode-qwen', 'Qwen 3.8 Max', 'opencode', 'qwen3.8-max',
          'OpenCode; $2/$6 per M on a $15 monthly cap'),
    Model('opencode-minimax', 'MiniMax M3', 'opencode', 'minimax-m3',
          'OpenCode; $0.30/$1.20 per M; reasoning wrapper stripped'),
    Model('opencode-longcat', 'LongCat 2.0', 'opencode', 'longcat-2.0',
          'OpenCode; $0.30/$1.20 per M'),
    Model('opencode-glm', 'GLM 5.3', 'opencode', 'glm-5.3',
          'OpenCode; text only, cannot look at slides'),
)

# Slide-check picker. Every entry below returned all five colour names for a test
# image, so the app knows the pixels reach the model. The lane is OpenCode, and it
# bills per token against a dollar limit per model — a slide check is real spend,
# so the notes quote what a 19-slide deck actually cost when measured.
#
# Measured on one real client deck (FADC, 19 slides, 0 errors), same prompt:
#   kimi-k3      15/19 slides flagged, 50 issues, ~9.2 min, ~$0.49 per deck
#   glm-5.3-flash 9/19 slides flagged, 25 issues, ~38 s,   ~$0.0092 per deck
#   qwen3.8-flash 9/19 slides flagged, 18 issues, ~174 s,  ~$0.0084 per deck
# All three caught the worst slide's title overlap; none of the cheap two caught
# the table running off that slide's bottom edge. K3 is not deterministic — rerun
# on that one slide it reported 1 issue where the deck run reported 4 — so treat
# the counts as a signal, not a ranking. Cheap models lead the list for cost and
# speed; K3 stays selectable for a deck that is about to go out.
VISION_MODELS: tuple[VisionModel, ...] = (
    VisionModel('glm-5.3-flash', 'GLM 5.3 Flash',
                'Recommended: ~1/53 of K3 per deck, whole deck in ~38 s'),
    VisionModel('qwen3.8-flash', 'Qwen 3.8 Flash',
                'Cheapest: ~1/58 of K3; caught 8 of its 10 high-severity slides'),
    VisionModel('kimi-k3', 'Kimi K3',
                'Thorough and dearest: ~$0.49 per deck, 77% of it output tokens'),
    VisionModel('deepseek-v4.1-flash', 'DeepSeek V4.1 Flash',
                'Sees slides; under-calls layout damage, so not the default'),
    VisionModel('qwen3.8-max', 'Qwen 3.8 Max', 'Sees slides and translates'),
    VisionModel('qwen3.7-plus', 'Qwen 3.7 Plus', 'Sees slides and translates'),
    VisionModel('longcat-2.0', 'LongCat 2.0',
                'Sees slides; returned empty on a deck-sized prompt'),
    VisionModel('minimax-m3', 'MiniMax M3', 'Sees slides; reasoning wrapper stripped'),
    VisionModel('deepseek-flash', 'DeepSeek Flash', 'Sees slides'),
    VisionModel('mimo-v2.5', 'MiMo 2.5', 'Sees slides; returned empty on a deck prompt'),
    VisionModel('omen-alpha', 'Omen Alpha', 'Sees slides'),
)

DEFAULT_TRANSLATE_KEY = 'gemini-25-flash-lite'
# Measured on the same three slides of a real client deck (FADC), where slide 3 has
# a genuine defect — bullet text spilling out of two boxes and colliding with the
# grey transition arrows:
#   gemini-3.5-flash      3/3 reviewed, 2 issues (overflow + overlap), high
#   kimi-k3               3/3 reviewed, 3 issues, quoting the exact spilled bullets
#   deepseek-v4.1-flash   3/3 reviewed, 1 issue — called the spilled text
#                         "cramped, low severity" and missed the arrow collision
# All three agree slides 1-2 are clean, so the difference is severity, not blindness.
# The whole-deck comparison then decided the default on price as well as coverage:
# kimi-k3 caught the most (15/19 flagged, 50 issues) but costs ~$0.49 a deck against
# ~$0.009 for the flash tier, which is the same allowance the coding lane draws on.
# So the cheap model leads the list and kimi-k3 is kept as the thorough option.
DEFAULT_VISION_MODEL = 'glm-5.3-flash'


class VisionCost(NamedTuple):
    """Published per-1M-token price for one OpenCode model, plus its monthly cap."""

    input_per_m: float
    output_per_m: float
    monthly_cap_usd: float


# Read off the Go plan's price table. Models the table does not list (deepseek-flash,
# omen-alpha) are absent on purpose: an unknown price reports as None rather than a
# made-up number.
VISION_COSTS: dict[str, VisionCost] = {
    'glm-5.3-flash': VisionCost(0.15, 0.50, 60),
    'qwen3.8-flash': VisionCost(0.15, 0.47, 30),
    'kimi-k3': VisionCost(3.00, 15.00, 15),
    'kimi-k2.7-code': VisionCost(0.95, 4.00, 60),
    'kimi-k2.6': VisionCost(0.95, 4.00, 60),
    'qwen3.8-max': VisionCost(2.00, 6.00, 15),
    'qwen3.7-plus': VisionCost(0.40, 1.60, 60),
    'longcat-2.0': VisionCost(0.30, 1.20, 60),
    'minimax-m3': VisionCost(0.30, 1.20, 60),
    'mimo-v2.5': VisionCost(0.14, 0.28, 60),
}


def vision_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Dollars for one call, or None when the plan publishes no price for it."""
    price = VISION_COSTS.get(model)
    if price is None:
        return None
    return ((prompt_tokens * price.input_per_m) + (completion_tokens * price.output_per_m)) / 1_000_000


def translate_keys() -> set[str]:
    return {entry.key for entry in TRANSLATE_MODELS}


def translate_model_ids() -> set[str]:
    return {entry.model for entry in TRANSLATE_MODELS}


def vision_model_ids() -> set[str]:
    return {entry.model for entry in VISION_MODELS}


def is_vision_model(model: str) -> bool:
    return model in vision_model_ids()


def catalog_payload() -> dict:
    """What `GET /api/models` returns."""
    return {
        'translate': [entry.as_dict() for entry in TRANSLATE_MODELS],
        'vision': [entry.as_dict() for entry in VISION_MODELS],
        'defaults': {'translate': DEFAULT_TRANSLATE_KEY, 'vision': DEFAULT_VISION_MODEL},
    }
