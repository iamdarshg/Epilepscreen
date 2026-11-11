"""Browser QA sweep for Epilepscreen.

Drives the real site with Playwright and writes screenshots to qa/:
  - every page at desktop (1440x900) and mobile (390x844)
  - the full demo journey: upload -> screen -> player -> add to cart -> checkout

Usage (uvicorn/django dev server must already be running):
    .venv/Scripts/python.exe scripts/qa_screens.py [base_url]

Exit code 1 if any page returned an error status or logged a console error.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'qa'
SAMPLE = ROOT / 'samples' / 'strobe.mp4'

DESKTOP = {'width': 1440, 'height': 900}
MOBILE_VIEWPORT = {'width': 390, 'height': 844}

problems = []
console_errors = []


def note(msg):
    print(f'  {msg}')


def check(cond, msg):
    if not cond:
        problems.append(msg)
        print(f'  FAIL {msg}')


def watch(page):
    page.on('console', lambda m: console_errors.append(m.text)
            if m.type == 'error' and 'favicon' not in m.text else None)
    page.on('pageerror', lambda e: console_errors.append(str(e)))


def shoot(page, name, full=True):
    path = OUT / f'{name}.png'
    page.screenshot(path=str(path), full_page=full)
    note(f'shot {path.relative_to(ROOT)}')


def visit(page, name, url, expect_text=None):
    response = page.goto(f'{BASE}{url}', wait_until='networkidle')
    status = response.status if response else 0
    check(status < 400, f'{name}: HTTP {status} for {url}')
    if expect_text:
        check(expect_text in page.content(), f'{name}: missing text {expect_text!r}')
    shoot(page, name)
    return response


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------------- desktop pass ----------------
        context = browser.new_context(viewport=DESKTOP, device_scale_factor=1)
        page = context.new_page()
        watch(page)

        print('desktop pages')
        visit(page, 'desktop-home', '/', 'Screen every video before it plays')
        visit(page, 'desktop-library', '/browse/', 'The library')
        visit(page, 'desktop-upload', '/upload/', 'Add a file to the library')
        visit(page, 'desktop-store', '/store/', 'The range')
        visit(page, 'desktop-checkout-empty', '/checkout/', 'cart is empty')

        # ---- upload a generated clip and let the Python screener run ----
        print('upload + screen')
        page.goto(f'{BASE}/upload/', wait_until='networkidle')
        page.set_input_files('#upload-file', str(SAMPLE))
        page.fill('#upload-title', 'Strobe test clip')
        page.check('#upload-screen')
        page.click('button[type="submit"]')
        page.wait_for_url('**/player/**', timeout=120000)
        page.wait_for_load_state('networkidle')
        check('Strobe test clip' in page.content(), 'player: uploaded title missing')
        check('Hazard windows' in page.content(), 'player: report section missing')

        # the overlay widget should be attached to the video
        page.wait_for_timeout(1500)
        overlay = page.evaluate(
            "() => !!document.querySelector('.epilepscreen-overlay')")
        check(overlay, 'player: overlay widget not attached')
        duration = page.evaluate(
            "() => document.getElementById('player-video').duration || 0")
        note(f'video duration reported by the browser: {duration}')
        check(duration > 0, 'player: the browser could not decode the clip')
        segments = page.evaluate(
            "() => document.querySelectorAll('.timeline__seg').length")
        note(f'timeline segments drawn: {segments}')
        check(segments > 0, 'player: timeline has no hazard segments')
        shoot(page, 'desktop-player')

        # click the first hazard timestamp, then read the media position
        seek = page.query_selector('[data-seek]')
        if seek:
            seek.click()
            page.wait_for_timeout(400)
            t = page.evaluate("() => document.getElementById('player-video').currentTime")
            note(f'seeked to {t:.2f}s')
            check(t > 0, 'player: seek did not move the video')
        page.click('[data-guard-toggle]')
        page.wait_for_timeout(300)
        page.click('[data-guard-toggle]')
        page.click('[data-next-hazard]')

        player_url = page.url
        video_hash = player_url.rstrip('/').split('/')[-1]
        visit(page, 'desktop-library-filled', '/browse/', 'Screened video')
        visit(page, 'desktop-screening', f'/screening/{video_hash}/', 'How this was measured')
        visit(page, 'desktop-player-again', f'/player/{video_hash}/', 'Protection')
        visit(page, 'desktop-embed', f'/embed/{video_hash}/', 'player-video')

        # ---- demo checkout journey ----
        print('demo checkout')
        page.goto(f'{BASE}/store/', wait_until='networkidle')
        page.click('.order button[type="submit"]')
        page.wait_for_url('**/checkout/**')
        page.wait_for_load_state('networkidle')
        check('DEMO CHECKOUT' in page.content(), 'checkout: demo label missing')
        check('card number' not in page.content().lower() or
              'no card details' in page.content().lower(),
              'checkout: card field found')
        fill_ok = page.query_selector('#checkout-email') is not None
        check(fill_ok, 'checkout: email field missing')
        shoot(page, 'desktop-checkout')
        page.fill('#checkout-email', 'student@example.com')
        page.click('form.summary button[type="submit"]')
        page.wait_for_load_state('networkidle')
        check('Order recorded' in page.content(), 'confirmation: heading missing')
        shoot(page, 'desktop-confirmation')

        # ---- responsive breakpoints on a couple of pages ----
        page.set_viewport_size({'width': 1024, 'height': 768})
        visit(page, 'tablet-player', f'/player/{video_hash}/', 'Protection')
        context.close()

        # ---------------- mobile pass ----------------
        print('mobile pages')
        mcontext = browser.new_context(viewport=MOBILE_VIEWPORT, device_scale_factor=2, is_mobile=True)
        mpage = mcontext.new_page()
        watch(mpage)
        visit(mpage, 'mobile-home', '/', 'Screen every video')
        visit(mpage, 'mobile-library', '/browse/', 'The library')
        visit(mpage, 'mobile-player', f'/player/{video_hash}/', 'Protection')
        visit(mpage, 'mobile-screening', f'/screening/{video_hash}/', 'How this was measured')
        visit(mpage, 'mobile-store', '/store/', 'The range')
        visit(mpage, 'mobile-upload', '/upload/', 'Add a file')
        mcontext.close()
        browser.close()

    print()
    if console_errors:
        print('console errors:')
        for msg in console_errors:
            print('  -', msg)
    print(f'{len(problems)} problem(s)')
    for problem in problems:
        print('  -', problem)
    return 1 if (problems or console_errors) else 0


if __name__ == '__main__':
    sys.exit(main())
