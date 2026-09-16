"""The catalog and the translator registry must agree.

The picker is rendered from `app/model_catalog.py`, but translations are routed by
`TranslationService.translators`. When those two drift the failure is silent and
expensive: the UI offers a label, the backend resolves a different key, and the
only clue is text that came back untranslated. That already happened in production
— the page still offered "Kimi K2.5" and "DeepSeek V4" long after the registry had
moved to kimi-k3 and deepseek-v4-flash.

These tests are the guard: they read both sides and fail on any disagreement.
"""
import pytest

from app.config import Settings
from app.model_catalog import (
    DEFAULT_TRANSLATE_KEY,
    DEFAULT_VISION_MODEL,
    TRANSLATE_MODELS,
    VISION_MODELS,
    catalog_payload,
    is_vision_model,
    vision_cost,
    vision_model_ids,
)
from app.translators.service import TranslationService


@pytest.fixture(scope='module')
def service() -> TranslationService:
    return TranslationService(Settings())


def test_every_translate_key_exists_in_the_registry(service):
    missing = sorted(entry.key for entry in TRANSLATE_MODELS
                     if entry.key not in service.translators)
    assert not missing, (
        f'catalog keys with no translator: {missing}. A dropdown entry that does not '
        f'exist in the registry silently falls through to the default model.'
    )


def test_translate_labels_name_the_model_actually_used(service):
    """The label is a promise about which model runs."""
    mismatched = []
    for entry in TRANSLATE_MODELS:
        translator = service.translators[entry.key]
        actual = getattr(translator, 'model', None)
        if actual != entry.model:
            mismatched.append((entry.key, entry.model, actual))
    assert not mismatched, (
        f'catalog model ID != translator model ID for {mismatched}. '
        f'Either fix the catalog or point the key at the right model.'
    )


def test_catalog_keys_and_models_are_unique():
    keys = [entry.key for entry in TRANSLATE_MODELS]
    models = [entry.model for entry in TRANSLATE_MODELS]
    assert len(keys) == len(set(keys)), 'duplicate translate keys in the catalog'
    assert len(models) == len(set(models)), 'duplicate translate model IDs in the catalog'
    vision_ids = [entry.model for entry in VISION_MODELS]
    assert len(vision_ids) == len(set(vision_ids)), 'duplicate vision models in the catalog'


def test_deepseek_v4_flash_is_gone():
    """Dropped on request. It also cannot read an image (HTTP 400), so it has no job
    left: v4.1-flash translates better and passes the slide check."""
    assert 'deepseek-v4-flash' not in {entry.model for entry in TRANSLATE_MODELS}
    assert 'deepseek-v4-flash' not in vision_model_ids()


def test_registry_no_longer_points_at_the_removed_model(service):
    used = {getattr(translator, 'model', None) for translator in service.translators.values()}
    assert 'deepseek-v4-flash' not in used, (
        'the registry still points a key at deepseek-v4-flash, which was removed from '
        'the app; every job using that key would translate with a model we no longer offer'
    )


def test_vision_list_excludes_the_models_that_cannot_see():
    """Both shipped models failed the image test with HTTP 400, so they must never be
    offered as slide-check models — a blind model invents layout findings."""
    assert 'deepseek-v4-flash' not in vision_model_ids()
    assert 'minimax-m2.5' not in vision_model_ids()


def test_defaults_are_offered():
    assert is_vision_model(DEFAULT_VISION_MODEL)
    assert DEFAULT_TRANSLATE_KEY in {entry.key for entry in TRANSLATE_MODELS}


def test_payload_shape_matches_what_the_page_consumes():
    payload = catalog_payload()
    assert set(payload) == {'translate', 'vision', 'defaults'}
    assert payload['defaults'] == {'translate': DEFAULT_TRANSLATE_KEY,
                                   'vision': DEFAULT_VISION_MODEL}
    for entry in payload['translate'] + payload['vision']:
        assert entry['label'] and entry['model']
        assert entry['lane'] in {'gemini', 'opencode'}
        assert entry['key'] in {'gemini-25-flash-lite', 'gemini-flash-lite', 'gemini-flash',
                                'gemini-flash-38', 'gemini-pro', 'opencode-deepseek',
                                'opencode-kimi', 'opencode-qwen', 'opencode-minimax',
                                'opencode-longcat', 'opencode-glm', *vision_model_ids()}


def test_vision_lane_is_opencode():
    """Every slide-check model runs on OpenCode, whose Go plan bills per token against
    a dollar limit per model. The lane matters because it decides what a deck costs."""
    assert {entry.as_dict()['lane'] for entry in VISION_MODELS} == {'opencode'}


def test_cost_table_prices_what_it_offers_and_admits_what_it_cannot():
    """The Go plan prices each model against its own dollar limit, so an estimate is
    only honest if it disappears when the plan publishes no price. The three models
    the price table omits must report None rather than a plausible-looking number.
    """
    unpriced = {'deepseek-v4.1-flash', 'deepseek-flash', 'omen-alpha'}
    for model in unpriced:
        assert vision_cost(model, 1000, 1000) is None, model
    for model in vision_model_ids() - unpriced:
        assert vision_cost(model, 1000, 1000) is not None, model
        assert vision_cost(model, 1000, 1000) > 0


def test_the_default_is_an_order_of_magnitude_cheaper_than_the_thorough_pick():
    """Why the default moved: on the per-slide token profile measured with kimi-k3
    (1987 in, 1304 out) the flash tier has to come in far below it, and kimi-k3 has to
    stay selectable — cheap by default, thorough on demand."""
    profile = (1987, 1304)
    cheap = vision_cost(DEFAULT_VISION_MODEL, *profile)
    dear = vision_cost('kimi-k3', *profile)

    assert is_vision_model('kimi-k3'), 'the thorough option must stay on the list'
    assert cheap * 20 < dear, (cheap, dear)

