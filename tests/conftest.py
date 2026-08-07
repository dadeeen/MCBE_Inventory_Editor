import pytest
from flask.testing import FlaskClient

from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.services import BedrockEditorService


@pytest.fixture(autouse=True, scope="session")
def _isolated_runtime_storage(tmp_path_factory):
    """Keep every test-session artifact outside the source tree."""

    runtime_root = tmp_path_factory.mktemp("mcbe-runtime")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("MCBE_DATA_ROOT", str(runtime_root / "data"))
        monkeypatch.setenv("MCBE_BACKUP_ROOT", str(runtime_root / "data" / "backups"))
        yield runtime_root


class GermanLocaleClient(FlaskClient):
    """Test client that requests the German (source-language) locale.

    Backend messages are translated per request locale; the suite asserts the
    German source strings. Tests that exercise translation explicitly send
    their own Accept-Language header or locale cookie, which takes precedence
    over this environ default.
    """

    def open(self, *args, **kwargs):
        environ_base = kwargs.setdefault("environ_base", {})
        if isinstance(environ_base, dict):
            environ_base.setdefault("HTTP_ACCEPT_LANGUAGE", "de")
        return super().open(*args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _german_api_locale_for_tests(_isolated_runtime_storage):
    try:
        import main
    except Exception:
        yield
        return
    previous = main.app.test_client_class
    main.app.test_client_class = GermanLocaleClient
    yield
    main.app.test_client_class = previous


@pytest.fixture(autouse=True)
def _isolate_in_memory_rate_limits():
    """Keep request counts and temporary test limits local to each test."""

    try:
        import main
    except Exception:
        yield
        return

    with main._RATE_LOCK:
        original_config = dict(main._RATE_CONFIG)
        main._RATE_LIMITS.clear()
    try:
        yield
    finally:
        with main._RATE_LOCK:
            main._RATE_LIMITS.clear()
            main._RATE_CONFIG.clear()
            main._RATE_CONFIG.update(original_config)


def _nbt_module():
    return pytest.importorskip("amulet_nbt", reason="amulet_nbt is required for NBT fixture tests")


def make_minimal_player_tag():
    nbt = _nbt_module()
    return nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
        }
    )


def make_player_bytes(item_tag):
    nbt = _nbt_module()
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item_tag]),
            "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0), nbt.DoubleTag(3.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
        }
    )
    return nbt.NamedTag(player).save_to(compressed=False, little_endian=True)


def make_full_player_tag(items=None):
    nbt = _nbt_module()
    tag = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
            "XPLevel": nbt.IntTag(5),
            "XPProgress": nbt.FloatTag(0.5),
            "foodLevel": nbt.IntTag(18),
            "foodSaturationLevel": nbt.FloatTag(15.0),
        }
    )
    if items:
        tag["Inventory"] = nbt.ListTag(items)
    return tag


class FakeDb:
    def __init__(self, _db_path):
        self.store = {}
        self.closed = False

    def get(self, key):
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]

    def put(self, key, value):
        self.store[key] = value

    def close(self):
        self.closed = True

    def iter_items(self):
        return list(self.store.items())


@pytest.fixture(autouse=True)
def _service_fake_read_factory(request, monkeypatch):
    if request.module.__name__ != "tests.test_service":
        return
    original_init = BedrockEditorService.__init__

    def test_init(self, items_db, enchantments_db, db_factory=LevelDbAdapter, readonly_db_factory=ReadonlyLevelDbAdapter):
        if readonly_db_factory is ReadonlyLevelDbAdapter and db_factory is not LevelDbAdapter:
            readonly_db_factory = db_factory
        return original_init(self, items_db, enchantments_db, db_factory=db_factory, readonly_db_factory=readonly_db_factory)

    monkeypatch.setattr(BedrockEditorService, "__init__", test_init)
