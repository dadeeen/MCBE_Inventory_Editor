from mcbe_editor.server_guard import ServerGuardStore


def test_new_process_store_rotates_shared_guard_and_existing_worker_converges(tmp_path):
    path = tmp_path / "server_guard_state.json"
    first_worker = ServerGuardStore(path)
    first_token = first_worker.current()

    restarted_worker = ServerGuardStore(path)
    restarted_token = restarted_worker.current()

    assert restarted_token
    assert restarted_token != first_token
    assert first_worker.current() == restarted_token


def test_online_observation_rotates_guard_for_every_worker(tmp_path):
    path = tmp_path / "server_guard_state.json"
    first_worker = ServerGuardStore(path)
    current = first_worker.current()
    second_worker = ServerGuardStore(path)
    current = second_worker.current()

    observation = first_worker.observe(online=True)

    assert observation.previous_token == current
    assert observation.token != current
    assert second_worker.current() == observation.token


def test_invalid_guard_state_is_replaced_atomically(tmp_path):
    path = tmp_path / "server_guard_state.json"
    store = ServerGuardStore(path)
    store.current()
    path.write_text("{invalid", encoding="utf-8")

    recovered = store.current()

    assert recovered
    assert ServerGuardStore(path).current() != recovered


def test_excessively_nested_guard_state_is_replaced(tmp_path):
    path = tmp_path / "server_guard_state.json"
    store = ServerGuardStore(path)
    original = store.current()
    path.write_text('{"nested":' * 10_000 + "null" + "}" * 10_000, encoding="utf-8")

    recovered = store.current()

    assert recovered
    assert recovered != original
