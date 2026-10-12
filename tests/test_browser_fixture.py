from scripts.browser_fixture import without_automatic_assets


def test_fixture_removes_automatic_assets_with_html_parsing():
    source = (
        '<!doctype html><LINK href="/style.css"><main>&lt;script&gt; &#38; &#x26;</main>'
        '<SCRIPT src="/app.js"></SCRIPT ><script>if (a < b) run();</script><p>Ready</p>'
    )
    assert without_automatic_assets(source) == "<!doctype html><main>&lt;script&gt; &#38; &#x26;</main><p>Ready</p>"


def test_fixture_can_keep_json_catalog_without_executable_scripts():
    catalog = '<script id="catalog" TYPE="application/json">{"label":"A & B"}</script>'
    source = catalog + '<script type="module">start();</script><script>run();</script><p>Ready</p>'
    assert without_automatic_assets(source, keep_json=True) == catalog + "<p>Ready</p>"
    assert without_automatic_assets(source) == "<p>Ready</p>"


def test_fixture_preserves_template_content_and_quoted_attributes():
    source = '<!-- fixture --><link title="a > b" href="/style.css"/><input value="&quot;test&quot;"/><p>Text</p>'
    assert without_automatic_assets(source) == '<!-- fixture --><input value="&quot;test&quot;"/><p>Text</p>'
