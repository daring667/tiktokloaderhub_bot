"""Tests for the menu surface and for settings actually reaching the code.

A preference that nothing reads is worse than no preference at all, so the
wiring is covered here rather than left to the handler suites.
"""
from types import SimpleNamespace

import pytest

from handlers import menu
from handlers.base import ignores_links_in_groups
from handlers.youtube import best_stream_within_limit
from services import user_settings as us


def _chat(kind):
    return SimpleNamespace(type=SimpleNamespace(name=kind))


def _message(kind="GROUP", user_id=42):
    return SimpleNamespace(chat=_chat(kind),
                           from_user=SimpleNamespace(id=user_id))


class TestGroupOptOut:

    def test_bot_reacts_in_groups_by_default(self, tmp_db):
        assert ignores_links_in_groups(tmp_db, _message()) is False

    def test_opting_out_silences_group_links(self, tmp_db):
        tmp_db.set_user_setting(42, "groups", us.GROUPS_OFF)
        assert ignores_links_in_groups(tmp_db, _message()) is True

    def test_direct_messages_are_never_silenced(self, tmp_db):
        """The switch is about shared chats, not about turning the bot off."""
        tmp_db.set_user_setting(42, "groups", us.GROUPS_OFF)
        assert ignores_links_in_groups(tmp_db, _message("PRIVATE")) is False

    def test_one_user_opting_out_does_not_affect_another(self, tmp_db):
        tmp_db.set_user_setting(42, "groups", us.GROUPS_OFF)
        assert ignores_links_in_groups(tmp_db, _message(user_id=99)) is False

    def test_a_group_admin_cannot_override_the_members_choice(self, tmp_db):
        """Settled behaviour, not an oversight (see AGENTS.md).

        The guard looks only at who wrote the message, so there is nothing an
        admin could set that would bring the bot back for someone else's links.
        """
        tmp_db.set_user_setting(42, "groups", us.GROUPS_OFF)
        admin_run_chat = SimpleNamespace(
            chat=_chat("SUPERGROUP"), from_user=SimpleNamespace(id=42))
        assert ignores_links_in_groups(tmp_db, admin_run_chat) is True

    def test_a_broken_database_does_not_silence_the_bot(self):
        class Broken:
            def get_user_settings(self, user_id):
                raise RuntimeError("db is down")
        assert ignores_links_in_groups(Broken(), _message()) is False

    def test_missing_pieces_are_tolerated(self, tmp_db):
        assert ignores_links_in_groups(None, _message()) is False
        assert ignores_links_in_groups(
            tmp_db, SimpleNamespace(chat=_chat("GROUP"), from_user=None)) is False


class TestQualityPresetReachesTheChooser:

    MB = 1024 * 1024

    def _streams(self):
        return [
            {"itag": "1080", "res": "1080p", "width": 1080, "height": 1920,
             "filesize": 21 * self.MB, "type": "video"},
            {"itag": "720", "res": "720p", "width": 720, "height": 1280,
             "filesize": 12 * self.MB, "type": "video"},
            {"itag": "360", "res": "360p", "width": 360, "height": 640,
             "filesize": 2 * self.MB, "type": "video"},
        ]

    @pytest.mark.parametrize("preset,expected", [
        (us.QUALITY_AUTO, "1080"),
        ("1080", "1080"),
        ("720", "720"),
        ("360", "360"),
    ])
    def test_preset_caps_what_is_sent(self, preset, expected):
        chosen = best_stream_within_limit(
            self._streams(), max_side=us.max_side_for(preset))
        assert chosen["itag"] == expected

    def test_ask_turns_the_automatic_choice_off(self):
        assert us.should_auto_send(us.QUALITY_ASK) is False


class TestAudioPresetMapping:

    def test_russian_keeps_the_language_filter(self):
        assert us.audio_lang_for(us.AUDIO_RU) == "ru"

    def test_original_drops_the_filter(self):
        """Empty lets language_preference decide, and that favours the original."""
        assert us.audio_lang_for(us.AUDIO_ORIGINAL) == ""


class TestMenuRendering:

    def test_keyboard_is_persistent_and_shows_both_entries(self):
        kb = menu.main_keyboard()
        assert kb.is_persistent is True
        assert kb.resize_keyboard is True
        texts = [getattr(b, "text", b) for row in kb.keyboard for b in row]
        assert texts == [menu.BTN_SETTINGS, menu.BTN_HELP]

    def test_no_button_opens_a_web_app(self):
        """The Mini App was removed in 1.10.0; nothing should reopen it."""
        kb = menu.main_keyboard()
        for row in kb.keyboard:
            for button in row:
                assert getattr(button, "web_app", None) is None

    def test_overview_shows_every_setting_with_its_current_value(self):
        text = menu.overview_text({"quality": "720"})
        for key in us.DEFAULTS:
            assert us.TITLES[key] in text
        assert us.label_for("quality", "720") in text
        assert us.label_for("audio", us.AUDIO_RU) in text

    def test_overview_of_a_fresh_user_shows_the_defaults(self):
        text = menu.overview_text({})
        assert us.label_for("quality", us.QUALITY_AUTO) in text

    def test_overview_has_a_button_per_setting_plus_reset(self):
        rows = menu.overview_markup().inline_keyboard
        assert len(rows) == len(us.DEFAULTS) + 1

    def test_option_screen_marks_the_current_choice(self):
        rows = menu.option_markup("quality", "720").inline_keyboard
        marked = [r[0].text for r in rows if r[0].text.startswith("✅")]
        assert marked == ["✅ " + us.label_for("quality", "720")]

    def test_option_screen_offers_every_value_and_a_way_back(self):
        rows = menu.option_markup("audio", us.AUDIO_RU).inline_keyboard
        assert len(rows) == len(us.OPTIONS["audio"]) + 1
        assert rows[-1][0].callback_data.endswith("back")

    @pytest.mark.parametrize("key", sorted(us.DEFAULTS))
    def test_callback_payloads_fit_telegrams_64_byte_limit(self, key):
        """Telegram rejects anything longer, and it fails at tap time."""
        rows = menu.option_markup(key, us.DEFAULTS[key]).inline_keyboard
        for row in rows:
            assert len(row[0].callback_data.encode("utf-8")) <= 64

    @pytest.mark.parametrize("key", sorted(us.DEFAULTS))
    def test_option_screen_explains_what_the_setting_does(self, key):
        assert us.HINTS[key] in menu.option_text(key)
