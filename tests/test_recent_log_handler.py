import logging


def test_recent_log_handler_caps_individual_message_size():
    import main

    handler = main.RecentLogHandler(capacity=2)
    record = logging.LogRecord("mcbe_editor.test", logging.INFO, __file__, 1, "x" * 5000, (), None)

    handler.emit(record)

    [entry] = handler.tail()
    assert entry["message"] == "x" * 4000 + "… [gekürzt]"
