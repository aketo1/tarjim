"""`tarjim source setup | test`."""

from __future__ import annotations

import time
import webbrowser

import numpy as np
from PIL import Image

from . import paths
from .say import fail, info, ok, step, warn
from .sources import SourceError, open_source


def setup(host: str | None, redirect_url: str | None, pin: str | None) -> int:
    """Link this laptop to the PS5. Each run does the next missing step."""
    from .sources import ps5

    cfg = paths.load_config()
    try:
        host = host or cfg.get("ps5_host")
        if not host:
            step("أدوّر على الـPS5 في الشبكة...")
            found = [f for f in ps5.discover() if f.host_type == "PS5"]
            if not found:
                fail("ما لقيت PS5 في الشبكة. تأكد إنه شغّال (مو في وضع الراحة) وعلى نفس الشبكة.")
                info("أو عطني عنوانه: tarjim source setup --host <عنوان الـPS5>")
                return 1
            host = found[0].host
            if len(found) > 1:
                warn(f"لقيت أكثر من جهاز، اخترت الأول: {', '.join(f.host for f in found)}")
        device = ps5.device_for(host)
        cfg["ps5_host"] = host
        cfg["ps5"] = {"name": device.host_name, "firmware": device.system_version, "mac": device.mac_address}
        paths.save_config(cfg)
        ok(f"الـPS5: {device.host_name} على {host} — النظام {device.system_version} — الحالة: {device.status_name}")

        linked = ps5.linked_users(device)
        if linked and not redirect_url and not pin:
            cfg["ps5_user"] = cfg.get("ps5_user") if cfg.get("ps5_user") in linked else linked[0]
            paths.save_config(cfg)
            ok(f"اللابتوب مربوط بالـPS5 بحساب: {cfg['ps5_user']}. جرّب: tarjim source test")
            return 0

        if redirect_url:
            name = ps5.add_user_from_redirect(redirect_url)
            ok(f"تم التعرّف على الحساب: {name}")

        pending = ps5.pending_users()
        if not pending:
            url = ps5.login_url()
            info("الخطوة 1: سجّل دخول بالحساب الثاني (مو حسابك اللي تلعب فيه) في صفحة Sony اللي بتفتح الحين.")
            info("بعد الدخول بتطلع صفحة فاضية مكتوب فيها redirect. انسخ عنوانها كامل من شريط المتصفح وعطني إياه.")
            info(f"لو ما فتحت الصفحة، افتح هذا الرابط:\n{url}")
            webbrowser.open(url)
            return 2

        user = pending[-1]
        if not pin:
            info(f"الخطوة 2: على الـPS5 وأنت داخل بالحساب الثاني ({user}):")
            info("الإعدادات ‹ النظام ‹ اللعب عن بُعد ‹ ربط جهاز. بيطلع رقم من 8 أرقام، عطني إياه (صالح 5 دقائق تقريباً).")
            return 2

        step("أربط اللابتوب بالـPS5...")
        ps5.link(device, user, pin)
        cfg["ps5_user"] = user
        paths.save_config(cfg)
        ok(f"تم الربط بحساب {user}. جرّب: tarjim source test")
        return 0
    except SourceError as exc:
        fail(str(exc))
        return 1


def test(backend: str, seconds: float, path: str | None, host: str | None) -> int:
    """Read frames for a while; report resolution, fps, gaps, drops and reconnects."""
    try:
        source = open_source(backend, path=path, host=host)
    except SourceError as exc:
        fail(str(exc))
        return 1
    step(f"أقرأ الصورة من المصدر ({backend}) لمدة {seconds:.0f} ثانية...")
    count = 0
    gaps: list[float] = []
    last_t = None
    sample = None
    t0 = time.monotonic()
    first_frame_at = None
    report_at = t0 + 10
    try:
        for frame, t_capture, _seq in source.frames():
            now = time.monotonic()
            if first_frame_at is None:
                first_frame_at = now
                info(f"أول صورة وصلت بعد {now - t0:.1f} ثانية: {frame.shape[1]}x{frame.shape[0]}")
            count += 1
            if last_t is not None:
                gaps.append(t_capture - last_t)
            last_t = t_capture
            sample = frame
            if now >= report_at:
                report_at = now + 10
                i = source.info()
                info(f"  {now - t0:5.0f}s  {i.fps:4.1f} fps  انقطاعات: {i.reconnects}")
            if now - (first_frame_at or t0) >= seconds:
                break
            if first_frame_at is None and now - t0 > 60:
                break
    except SourceError as exc:
        fail(f"المصدر توقف: {exc}")
        source.close()
        return 1
    except KeyboardInterrupt:
        pass
    result = source.info()
    last_error = getattr(source, "last_error", None)
    source.close()
    if count == 0 or sample is None:
        fail(f"ما وصلت ولا صورة. {last_error or ''}")
        return 1
    elapsed = max(1e-6, (last_t or 0) - (first_frame_at or 0)) if count > 1 else 0.0
    fps = (count - 1) / elapsed if elapsed > 0 else 0.0
    g = np.array(gaps) * 1000 if gaps else np.array([0.0])
    out = paths.REPO / "out"
    out.mkdir(exist_ok=True)
    shot = out / f"source-{backend}-{time.strftime('%Y%m%d-%H%M%S')}.png"
    Image.fromarray(np.ascontiguousarray(sample[:, :, ::-1])).save(shot)
    black = float(sample.mean()) < 3.0
    ok(f"الدقة: {result.width}x{result.height}")
    ok(f"الصور: {count} خلال {elapsed:.1f} ثانية = {fps:.1f} صورة/ثانية")
    info(f"الفاصل بين الصور: وسيط {np.median(g):.0f} ms، p90 {np.percentile(g, 90):.0f} ms، أقصى {g.max():.0f} ms")
    info(f"صور فاتتني: {result.dropped} — إعادة اتصال: {result.reconnects}")
    info(f"آخر صورة محفوظة: {shot}")
    if black:
        warn("الصورة سوداء تماماً (ممكن اللعبة تمنع البث في هذا المشهد).")
    passed = fps >= 25 and result.height >= 720
    if backend != "file" and not passed:
        warn("أقل من المطلوب (25 صورة/ثانية و 720p على الأقل).")
        return 1
    return 0
