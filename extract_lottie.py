import asyncio
import json
import os
from playwright.async_api import async_playwright

USER_DATA_DIR = os.path.abspath("vk_profile")
SAVE_DIR = os.path.abspath("lottie_out")
os.makedirs(SAVE_DIR, exist_ok=True)

TARGET_URL = (
    "https://vk.ru/id737474718"
    "?w=%2Fgifts_catalog%3Frecipient_ids%3D737474718%26ref%3Dprofile_button"
)

INIT_SCRIPT = r"""
(() => {
    if (window.__lottieHooked) return;
    window.__lottieHooked = true;

    function looksLikeLottie(obj) {
        return obj && typeof obj === 'object'
            && ('layers' in obj) && ('v' in obj)
            && ('fr' in obj) && ('ip' in obj);
    }

    function send(obj, source) {
        try {
            if (looksLikeLottie(obj) && typeof window.lottieSaver === 'function') {
                window.lottieSaver(source, JSON.stringify(obj));
                console.log('[LOTTIE-CAPTURE] -> sent, layers=',
                            (obj.layers || []).length);
            }
        } catch (e) {
            console.log('[LOTTIE-CAPTURE] send error:', e.message);
        }
    }

    const origParse = JSON.parse;
    JSON.parse = function(t, r) {
        const v = origParse.call(this, t, r);
        send(v, 'JSON.parse');
        return v;
    };

    if (window.Response && Response.prototype.json) {
        const origJson = Response.prototype.json;
        Response.prototype.json = function() {
            return origJson.call(this).then(d => { send(d, 'Response.json'); return d; });
        };
    }

    if (window.fetch) {
        const origFetch = window.fetch;
        window.fetch = function(...a) {
            return origFetch.apply(this, a).then(resp => {
                try {
                    const c = resp.clone();
                    c.text().then(t => {
                        try { send(origParse.call(JSON, t), 'fetch'); } catch(e){}
                    }).catch(()=>{});
                } catch(e){}
                return resp;
            });
        };
    }

    if (window.XMLHttpRequest) {
        const oOpen = XMLHttpRequest.prototype.open;
        const oSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function(m,u,...r){ this.__url=u; return oOpen.call(this,m,u,...r); };
        XMLHttpRequest.prototype.send = function(...a){
            this.addEventListener('load', function(){
                try {
                    const t = this.responseText;
                    if (!t) return;
                    send(origParse.call(JSON, t), 'XHR:' + (this.__url||''));
                } catch(e){}
            });
            return oSend.apply(this, a);
        };
    }

    console.log('[LOTTIE-CAPTURE] hooked');
})();
"""


async def main():
    captured = []
    seen = set()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # ⚠️ Playwright передаёт первым аргументом служебный объект source
        # (информация о фрейме), потом уже наши аргументы из JS.
        def on_lottie(source, source_tag, json_str):
            try:
                data = json.loads(json_str)
            except Exception as e:
                # Теперь сюда попадают только реальные ошибки JSON
                print(f"[!] JSON parse fail ({source_tag}): {e}")
                return
            n = len(data.get("layers", []))
            h = hash(json_str)
            if h in seen:
                return
            seen.add(h)
            captured.append({"source": source_tag, "data": data})
            print(f"[+] Python поймал Lottie из {source_tag} — "
                  f"layers={n}, всего={len(captured)}")

        await page.expose_binding("lottieSaver", on_lottie)
        await page.add_init_script(INIT_SCRIPT)

        page.on("console", lambda m: print(f"[browser] {m.text}")
                if ("LOTTIE" in m.text or "error" in m.text.lower()) else None)

        # --- Авторизация
        print("[*] Открываем vk.ru...")
        await page.goto("https://vk.ru/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        if not await page.evaluate("() => !document.querySelector('#index_login_form, .LoginForm')"):
            print("[!] Войдите вручную и нажмите ENTER.")
            input()
        else:
            print("[+] Авторизованы.")

        # --- Каталог подарков
        print("\n[*] Переходим в каталог подарков...")
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        print("[*] Ждём canvas...")
        try:
            await page.wait_for_selector(
                "canvas[data-testid='lottie']", timeout=60000, state="attached"
            )
            print("[+] ✅ Canvas Lottie появился!")
        except Exception as e:
            print(f"[!] Canvas не найден: {e}")

        # --- Скролл
        print("\n[*] Скроллим каталог...")
        for i in range(12):
            await page.mouse.wheel(0, 700)
            await asyncio.sleep(1.2)
            if i % 3 == 0:
                print(f"    прогресс скролла, Python поймал: {len(captured)}")
        await asyncio.sleep(3)

        # --- Сохраняем
        print(f"\n[*] Сохраняем {len(captured)} анимаций в {SAVE_DIR} ...")
        captured.sort(key=lambda x: len(x["data"].get("layers", [])), reverse=True)
        for i, item in enumerate(captured, start=1):
            n = len(item["data"].get("layers", []))
            fname = os.path.join(SAVE_DIR, f"sticker_{i:03d}_layers{n}.json")
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(item["data"], f, ensure_ascii=False)
        print(f"[+] ✅ Сохранено файлов: {len(captured)}")

        print("\n" + "=" * 60)
        print(f"[*] ИТОГО: {len(captured)} уникальных Lottie-анимаций")
        print(f"[*] Папка: {SAVE_DIR}")
        print("=" * 60)
        input("[*] Нажмите ENTER, чтобы закрыть браузер...")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())