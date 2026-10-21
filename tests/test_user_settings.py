"""Tests for per-user download preferences.

The spec half is pure, so it is tested without a database; the storage half
goes through the real SQLite wrapper via the `tmp_db` fixture.
"""
import pytest

from services import user_settings as us


class TestNormalize:

    def test_empty_input_gives_the_defaults(self):
        assert us.normalize({}) == us.DEFAULTS
        assert us.normalize(None) == us.DEFAULTS

    def test_defaults_are_the_owners_choice(self):
        """Max quality within the 50 MB limit, Russian audio, groups on."""
        assert us.DEFAULTS["quality"] == us.QUALITY_AUTO
        assert us.DEFAULTS["audio"] == us.AUDIO_RU
        assert us.DEFAULTS["groups"] == us.GROUPS_ON

    def test_a_stored_value_wins_over_the_default(self):
        assert us.normalize({"quality": "720"})["quality"] == "720"

    def test_unknown_key_is_dropped(self):
        assert "colour" not in us.normalize({"colour": "red"})

    def test_retired_value_falls_back_to_the_default(self):
        """A row can outlive the option it names; it must not strand anyone."""
        result = us.normalize({"quality": "4320", "audio": "klingon"})
        assert result["quality"] == us.QUALITY_AUTO
        assert result["audio"] == us.AUDIO_RU

    def test_other_keys_survive_one_bad_value(self):
        result = us.normalize({"quality": "nonsense", "audio": us.AUDIO_ORIGINAL})
        assert result["quality"] == us.QUALITY_AUTO
        assert result["audio"] == us.AUDIO_ORIGINAL

    def test_normalize_does_not_mutate_the_defaults(self):
        us.normalize({"quality": "360"})
        assert us.DEFAULTS["quality"] == us.QUALITY_AUTO


class TestQualityMapping:

    def test_auto_means_no_cap(self):
        assert us.max_side_for(us.QUALITY_AUTO) is None

    def test_ask_means_no_cap_either(self):
        """"Ask" is handled by not choosing at all, not by a cap."""
        assert us.max_side_for(us.QUALITY_ASK) is None

    def test_a_number_caps_the_short_side(self):
        assert us.max_side_for("720") == 720
        assert us.max_side_for("360") == 360

    def test_garbage_means_no_cap(self):
        assert us.max_side_for("huge") is None
        assert us.max_side_for(None) is None

    def test_only_ask_switches_auto_send_off(self):
        assert us.should_auto_send(us.QUALITY_AUTO) is True
        assert us.should_auto_send("720") is True
        assert us.should_auto_send(us.QUALITY_ASK) is False


class TestGroups:

    def test_groups_are_on_by_default(self):
        assert us.reacts_in_groups({}) is True

    def test_opting_out_is_respected(self):
        assert us.reacts_in_groups({"groups": us.GROUPS_OFF}) is False

    def test_a_broken_value_keeps_the_bot_working(self):
        assert us.reacts_in_groups({"groups": "maybe"}) is True


class TestOptionsAreRenderable:
    """The settings screens build their buttons straight from OPTIONS."""

    @pytest.mark.parametrize("key", sorted(us.DEFAULTS))
    def test_every_setting_has_options_a_title_and_a_hint(self, key):
        assert us.OPTIONS.get(key), key
        assert us.TITLES.get(key), key
        assert us.HINTS.get(key), key

    @pytest.mark.parametrize("key", sorted(us.DEFAULTS))
    def test_the_default_is_one_of_the_offered_options(self, key):
        assert us.DEFAULTS[key] in us.valid_values(key)

    @pytest.mark.parametrize("key", sorted(us.DEFAULTS))
    def test_option_values_are_unique(self, key):
        values = us.valid_values(key)
        assert len(values) == len(set(values)), key

    def test_label_for_known_value(self):
        assert us.label_for("audio", us.AUDIO_RU) == "Русская дорожка"

    def test_label_for_unknown_value_is_not_an_error(self):
        assert us.label_for("audio", "klingon") == "klingon"


class TestSettingsStorage:

    def test_a_new_user_has_nothing_stored(self, tmp_db):
        assert tmp_db.get_user_settings(555) == {}

    def test_a_new_user_still_gets_the_defaults(self, tmp_db):
        assert us.normalize(tmp_db.get_user_settings(555)) == us.DEFAULTS

    def test_set_then_read(self, tmp_db):
        tmp_db.set_user_setting(555, "quality", "720")
        assert tmp_db.get_user_settings(555) == {"quality": "720"}

    def test_setting_again_replaces_rather_than_duplicates(self, tmp_db):
        tmp_db.set_user_setting(555, "quality", "720")
        tmp_db.set_user_setting(555, "quality", "360")
        assert tmp_db.get_user_settings(555) == {"quality": "360"}

    def test_settings_are_per_user(self, tmp_db):
        tmp_db.set_user_setting(1, "quality", "720")
        tmp_db.set_user_setting(2, "quality", "360")
        assert tmp_db.get_user_settings(1)["quality"] == "720"
        assert tmp_db.get_user_settings(2)["quality"] == "360"

    def test_keys_do_not_overwrite_each_other(self, tmp_db):
        tmp_db.set_user_setting(1, "quality", "720")
        tmp_db.set_user_setting(1, "audio", us.AUDIO_ORIGINAL)
        assert tmp_db.get_user_settings(1) == {
            "quality": "720", "audio": us.AUDIO_ORIGINAL}

    def test_reset_returns_the_user_to_defaults(self, tmp_db):
        tmp_db.set_user_setting(1, "quality", "360")
        tmp_db.reset_user_settings(1)
        assert tmp_db.get_user_settings(1) == {}
        assert us.normalize(tmp_db.get_user_settings(1)) == us.DEFAULTS

    def test_reset_leaves_other_users_alone(self, tmp_db):
        tmp_db.set_user_setting(1, "quality", "360")
        tmp_db.set_user_setting(2, "quality", "720")
        tmp_db.reset_user_settings(1)
        assert tmp_db.get_user_settings(2) == {"quality": "720"}

    def test_bulk_read(self, tmp_db):
        tmp_db.set_user_setting(1, "quality", "720")
        tmp_db.set_user_setting(2, "audio", us.AUDIO_ORIGINAL)
        assert tmp_db.get_settings_for_users([1, 2, 3]) == {
            1: {"quality": "720"},
            2: {"audio": us.AUDIO_ORIGINAL},
            3: {},
        }

    def test_bulk_read_of_nothing(self, tmp_db):
        assert tmp_db.get_settings_for_users([]) == {}

    def test_settings_survive_a_reopen(self, tmp_db):
        """Preferences are the kind of state a restart must not lose."""
        from services.database import BotDatabase
        tmp_db.set_user_setting(7, "quality", "1080")
        path = tmp_db.db_path
        tmp_db.close()
        reopened = BotDatabase(path)
        try:
            assert reopened.get_user_settings(7) == {"quality": "1080"}
        finally:
            reopened.close()
