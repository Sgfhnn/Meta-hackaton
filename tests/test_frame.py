"""POST /frame and birr/frame.py on generated pictures only (no real photos in tests)."""

import io
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from birr import frame


def notes_picture(size=(640, 480), box=(60, 50, 580, 430), seed=1) -> Image.Image:
    """A plain table with a busy, note-like printed rectangle on it."""
    rng = random.Random(seed)
    im = Image.new("RGB", size, (150, 110, 70))
    draw = ImageDraw.Draw(im)
    draw.rectangle(box, fill=(200, 215, 190))
    x0, y0, x1, y1 = box
    for _ in range(900):
        x, y = rng.randint(x0, x1 - 12), rng.randint(y0, y1 - 12)
        shade = rng.randint(10, 240)
        draw.line(
            (x, y, x + rng.randint(3, 12), y + rng.randint(-6, 6)), fill=(shade,) * 3, width=1
        )
    return im


def jpeg(im: Image.Image, quality=40) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def status(im: Image.Image) -> str:
    return frame.check(jpeg(im)).status


def test_a_clear_picture_is_ok():
    result = frame.check(jpeg(notes_picture()))
    assert result.status == "ok" and result.ready


def test_dark_bright_blurry_and_empty():
    im = notes_picture()
    assert status(ImageEnhance.Brightness(im).enhance(0.12)) == "dark"
    assert status(ImageEnhance.Brightness(im).enhance(3.0)) == "bright"
    assert status(im.filter(ImageFilter.GaussianBlur(6))) == "blurry"
    assert status(Image.new("RGB", (640, 480), (150, 110, 70))) == "no_notes"


def test_a_white_cloth_is_not_glare():
    assert status(Image.new("RGB", (640, 480), (222, 220, 214))) == "no_notes"


def test_far_and_cut_off():
    assert status(notes_picture(box=(280, 200, 360, 260))) == "far"
    cut = frame.check(jpeg(notes_picture(box=(400, 60, 640, 420))))
    assert cut.status == "cut_off" and cut.side == "right" and not cut.ready


def test_a_full_frame_of_notes_is_not_cut_off():
    """Hand-held photos often fill the frame; that is fine to count."""
    assert status(notes_picture(box=(0, 0, 640, 480))) == "ok"


def test_not_an_image_is_rejected():
    try:
        frame.check(b"not a jpeg")
    except frame.BadFrame:
        return
    raise AssertionError("expected BadFrame")


def test_frame_endpoint(client):
    files = {"image": ("f.jpg", jpeg(notes_picture()), "image/jpeg")}
    r = client.post("/frame", data={"lang": "en"}, files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["ready"] is True
    assert body["speech"]["en"] == "Good. Hold still."


def test_frame_endpoint_speaks_amharic(client):
    dark = ImageEnhance.Brightness(notes_picture()).enhance(0.1)
    r = client.post(
        "/frame", data={"lang": "am"}, files={"image": ("f.jpg", jpeg(dark), "image/jpeg")}
    )
    body = r.json()
    assert body["status"] == "dark" and body["ready"] is False
    assert body["speech"]["am"] == "በጣም ጨለማ ነው። ብርሃን ወዳለበት ቦታ ይሂዱ።"
    assert "speech_todo" not in body


def test_frame_endpoint_rejects_garbage(client):
    r = client.post("/frame", files={"image": ("f.jpg", b"nope", "image/jpeg")})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
