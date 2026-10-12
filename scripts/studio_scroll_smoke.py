"""Offline Chromium smoke test for Studio's scroll and world-result layout.

Run with: python scripts/studio_scroll_smoke.py
Requires jinja2 and playwright with Chromium (no Flask or Bedrock world needed).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
APP_CONFIG = {
    "mode": "local",
    "distribution": {"kind": "SOURCE", "project_version": "dev", "app_root": "/example"},
    "data_root_status": {"path": "/example"},
    "auth_enabled": False,
}


def render_template():
    def t(value, **params):
        return str(value).format(**params)

    html = (
        Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
        .get_template("index.html")
        .render(
            app_locale="de",
            t=t,
            url_for=lambda name, **params: "/static/" + params["filename"] if name == "static" else "/" + name,
            csrf_token="preview",
            app_config=APP_CONFIG,
            i18n_catalog={},
        )
    )
    return re.sub(r"<script\b[^>]*>[\s\S]*?</script>|<link\b[^>]*>", "", html)


def main():
    checks = 0
    with sync_playwright() as playwright:
        chromium_path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox"] if os.name == "posix" else [],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 960})
        page.set_content(render_template())
        for asset in ["style.css", "layout_variants.css", "focus_workspace.css"]:
            page.add_style_tag(content=(ROOT / "static" / asset).read_text(encoding="utf-8"))
        page.add_script_tag(content=(ROOT / "static" / "world_cards_view.js").read_text(encoding="utf-8"))
        page.evaluate("""() => {
            document.getElementById('worldPicker').style.display='block';
            document.body.dataset.workflowView='world';
            const names=['TameWorld2','Ausrüstung Equipped','Dennis-Testwelt','Meine Survival-Welt',
              'Nether-Projekte','MC Bedrock 02','Testworld','Spruce Cabin','Berg Dorf','Erkundung'];
            const worlds=names.map((name,i)=>({name,path:`/worlds/${i}`,folder:`Ordner${i}`}));
            window.showTestWorlds=(count, multipleSources=false)=>{
                window.MCBEWorldCardsView.applyWorldCardsRender({
                    worldList: document.getElementById('worldList'),
                    emptyEl: document.getElementById('worldScanEmpty'),
                    worldCountHint: document.getElementById('worldCountHint'),
                },Array.from({length:count},(_,i)=>({...worlds[i % worlds.length],path:`/worlds/${i}`})),{
                    sourceLabelForWorld: world=>multipleSources
                        ? (parseInt(world.path.split('/').pop(),10)%2 ? 'Andere Quellen' : 'Minecraft-Standardordner')
                        : 'Minecraft-Standardordner',
                    formatModified:()=> 'zuletzt geändert 08.10.2026',
                });
            };
            window.showTestWorlds(10);
        }""")
        sizes = [
            (390, 800),
            (900, 900),
            (1180, 900),
            (1181, 900),
            (1200, 900),
            (1366, 900),
            (1440, 900),
            (1600, 960),
            (1849, 1112),
            (1920, 1080),
            (1600, 750),
            (1181, 650),
        ]
        for layout in ("studio", "focus", "classic"):
            for width, height in sizes:
                page.set_viewport_size({"width": width, "height": height})
                for selected in (False, True):
                    page.evaluate(
                        """([layout, selected]) => {
                        document.documentElement.dataset.layout=layout;
                        document.documentElement.dataset.theme='dark';
                        const bar=document.getElementById('selectedWorldBar');
                        bar.style.display=selected?'flex':'none';
                        window.scrollTo(0,0);
                    }""",
                        [layout, selected],
                    )
                    values = page.evaluate("""() => {
                        const d=document.documentElement,
                            l=document.getElementById('worldList'),
                            g=l.querySelector('.world-source-group'),
                            rail=document.querySelector('.layout-controls'),
                            load=document.getElementById('btnLoad'),
                            bar=document.getElementById('selectedWorldBar'),
                            picker=document.getElementById('worldPicker');
                        return {
                            pageRange:d.scrollHeight-innerHeight,
                            horizontalRange:d.scrollWidth-innerWidth,
                            railRange:rail.scrollHeight-rail.clientHeight,
                            listRange:l.scrollHeight-l.clientHeight,
                            sourceGroupDisplay:getComputedStyle(g).display,
                            sourceGroupDirection:getComputedStyle(g).flexDirection,
                            firstCardWidth:g.querySelector('.world-card').getBoundingClientRect().width,
                            groupWidth:g.getBoundingClientRect().width,
                            listVisible:getComputedStyle(picker).display!=='none',
                            loadAboveList:bar.getBoundingClientRect().bottom<=l.getBoundingClientRect().top,
                            loadVisible:getComputedStyle(bar).display!=='none',
                        };
                    }""")
                    assert values["horizontalRange"] <= 1, (layout, width, height, selected, values)
                    if layout == "studio" and width >= 1366 and height >= 900 and not selected:
                        assert values["pageRange"] <= 1, ("unexpected page scrollbar", width, height, values)
                        if width >= 1440:
                            assert values["listRange"] > 0, ("the original full-width cards must scroll internally", width, height, values)
                        assert values["railRange"] <= 1, ("unexpected sidebar scrollbar", width, height, values)
                    if layout == "studio" and width >= 1181:
                        assert values["sourceGroupDisplay"] == "flex" and values["sourceGroupDirection"] == "column", (
                            "original single-column world list",
                            width,
                            height,
                            values,
                        )
                        assert abs(values["firstCardWidth"] - values["groupWidth"]) <= 2, ("full-width world cards", width, height, values)
                    if layout == "studio" and width >= 1181 and selected:
                        assert values["loadVisible"] and values["loadAboveList"], ("world load location", width, height, values)
                    checks += 1

        # The world chooser must remain scrollable for many results; do not just hide scrollbars.
        page.set_viewport_size({"width": 1600, "height": 960})
        page.evaluate("""() => { document.documentElement.dataset.layout='studio';
          document.getElementById('selectedWorldBar').style.display='none';
          window.showTestWorlds(80); }""")
        many = page.evaluate("""() => {
          const l=document.getElementById('worldList');l.scrollTop=500;
          return {scrollRange:l.scrollHeight-l.clientHeight, scrollTop:l.scrollTop};
        }""")
        assert many["scrollRange"] > 0 and many["scrollTop"] > 0, many
        checks += 1
        # Source group headings still occupy full rows in grouped results.
        page.evaluate("""() => window.showTestWorlds(10,true)""")
        groups = page.evaluate("""() => [...document.querySelectorAll('#worldList .world-source-group')].map(group=>{
          const title=group.querySelector('.world-source-title');const cards=[...group.querySelectorAll('.world-card')];
          return {cardCount:cards.length, titleTop:title.getBoundingClientRect().top,
            firstCardTop:cards[0].getBoundingClientRect().top,
            firstCardLeft:cards[0].getBoundingClientRect().left,
            secondCardLeft:cards[1].getBoundingClientRect().left,
            secondCardTop:cards[1].getBoundingClientRect().top,
            direction:getComputedStyle(group).flexDirection}
        })""")
        assert len(groups) == 2 and all(
            g["cardCount"] == 5
            and g["titleTop"] < g["firstCardTop"]
            and g["direction"] == "column"
            and abs(g["firstCardLeft"] - g["secondCardLeft"]) <= 2
            and g["secondCardTop"] > g["firstCardTop"]
            for g in groups
        ), groups
        checks += 1
        browser.close()
    print(f"Studio world-scroll smoke: {checks} checks passed")


if __name__ == "__main__":
    main()
