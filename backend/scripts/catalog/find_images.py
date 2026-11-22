"""Bước 4: ảnh thật, chính diện cho từng mục catalog.

``search`` (tốn credit Tavily + OpenRouter) với mỗi mục:

1. Lấy ứng viên: ảnh mặt trước bao bì của Open Food Facts cho sản phẩm đóng gói, còn lại Tavily ``/search`` có
   ``include_images``. Chưa có ứng viên đạt ``GOOD_SCORE`` thì tìm thêm bằng tên tiếng Anh.
2. Tải qua ``fetch_remote_image`` (chặn mạng riêng, giới hạn dung lượng, giải mã lại WebP), bỏ ảnh cạnh ngắn dưới
   500 px hoặc khung quá dẹt.
3. Model nhìn ảnh chấm tối đa 8 ứng viên trong một lượt: đúng món, một suất, góc chụp, chữ/watermark, người/tay,
   ảnh ghép, chất lượng, và khung bao món chính. Code loại ứng viên vi phạm và tính điểm.
4. Cắt vuông quanh khung bao (lề 35 %), 800 px. Ảnh trùng gần (dHash) với mục khác bị bỏ, lấy ứng viên kế tiếp.

``review`` ghi ``review.html`` (ảnh chọn + ứng viên dự phòng). ``image_overrides.json`` (commit) đổi lựa chọn:
``{"<key>": 3}`` (chỉ số ứng viên), ``{"<key>": "https://..."}`` (ảnh tự chọn) hoặc ``{"<key>": null}`` (bỏ ảnh).
``upload`` đưa ảnh đã chọn lên Cloudinary, public_id ``<folder>/foods/catalog/<sha1>`` như ảnh catalog hiện có.

    python -m scripts.catalog.find_images search --items items.json --limit 20
    python -m scripts.catalog.find_images review
    python -m scripts.catalog.find_images upload
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import HTTPException
from PIL import Image

from scripts.catalog.common import (
    CACHE,
    HERE,
    chat_json,
    image_part,
    model_client,
    read_json,
    write_json,
)

OUT = CACHE / "images.json"
CANDIDATES = CACHE / "candidates"
CROPS = CACHE / "crops"
OVERRIDES = HERE / "image_overrides.json"
MODEL = "google/gemma-4-31b-it"
MAX_CANDIDATES = 8
IMAGES_PER_CALL = 4
GOOD_SCORE = 12  # quality 4, góc trên/chéo, một suất: đủ tốt để không tìm thêm
MIN_SIDE, SIDE = 500, 800
DUPLICATE_BITS = 6

PROMPT = """Bạn chọn ảnh minh hoạ cho mục "{name}" ({name_en}) trong app ghi bữa ăn. Có {count} ảnh, đánh số theo thứ tự 1..{count}.
Với MỖI ảnh trả về một object:
- index: số thứ tự ảnh.
- is_target: true nếu ảnh thực sự là "{name}" ({kind_hint}), false nếu là món/sản phẩm khác, hình vẽ, ảnh minh hoạ không phải ảnh chụp.
- single_serving: true nếu là một phần/một món chính rõ ràng (không phải cả bàn nhiều món).
- view: "top" (chụp từ trên xuống), "angle" (chéo khoảng 45°, thấy rõ món), "side" (ngang), "close" (cận cảnh mất bố cục).
- text_or_watermark: true nếu có chữ chèn, logo, watermark, giá tiền, khung viền.
- people_or_hands: true nếu có người, mặt người hoặc bàn tay chiếm chỗ đáng kể.
- collage: true nếu là ảnh ghép nhiều khung.
- quality: 1–5 (độ nét, ánh sáng, hấp dẫn, món chiếm phần lớn khung hình).
- box: [x_min, y_min, x_max, y_max] khung bao món chính, toạ độ chuẩn hoá 0–1000 theo chiều rộng/chiều cao ảnh đó.
Trả về DUY NHẤT một JSON array."""

KIND_HINT = {"dish": "món ăn đã nấu, trình bày để ăn", "food": "thực phẩm, nguyên liệu như khi mua hoặc khi ăn",
             "product": "sản phẩm đóng gói, thấy rõ bao bì mặt trước"}


def safe(key: str) -> str:
    return key.replace(":", "_").replace("/", "_")


def dhash(image: Image.Image) -> int:
    pixels = image.convert("L").resize((9, 8)).tobytes()
    return sum(1 << index for index in range(64) if pixels[(index // 8) * 9 + index % 8] > pixels[(index // 8) * 9 + index % 8 + 1])


def score(verdict: dict, width: int, height: int) -> float | None:
    """Điểm của một ứng viên, hoặc None khi vi phạm tiêu chí bắt buộc."""
    if not verdict.get("is_target") or verdict.get("text_or_watermark") or verdict.get("collage") \
            or verdict.get("people_or_hands"):
        return None
    quality = verdict.get("quality") if isinstance(verdict.get("quality"), (int, float)) else 1
    value = 2.0 * quality + {"top": 2.5, "angle": 2.5, "side": 0.5, "close": 0.0}.get(verdict.get("view"), 0)
    value += 1.0 if verdict.get("single_serving") else -2.0
    value += min(min(width, height), 1200) / 1200
    return round(value, 2)


def crop_square(image: Image.Image, box) -> Image.Image:
    """Hình vuông quanh khung bao món (lề 35 % để thấy cả đĩa/bát), nằm trong ảnh; khung không hợp lệ thì cắt giữa."""
    width, height = image.size
    side = min(width, height)
    cx, cy = width / 2, height / 2
    if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
        x1, y1, x2, y2 = (box[0] * width / 1000, box[1] * height / 1000, box[2] * width / 1000, box[3] * height / 1000)
        if x2 - x1 > width * 0.1 and y2 - y1 > height * 0.1:
            side = min(max(x2 - x1, y2 - y1) * 1.35, width, height)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    left = min(max(cx - side / 2, 0), width - side)
    top = min(max(cy - side / 2, 0), height - side)
    square = image.crop((round(left), round(top), round(left + side), round(top + side)))
    return square.resize((SIDE, SIDE), Image.LANCZOS) if square.width > SIDE else square


async def tavily_images(client: httpx.AsyncClient, query: str) -> list[dict]:
    response = await client.post("https://api.tavily.com/search", json={
        "query": query, "max_results": 10, "search_depth": "basic", "include_images": True,
        "include_image_descriptions": True}, timeout=40)
    response.raise_for_status()
    rows = []
    for image in response.json().get("images", []):
        url, description = (image.get("url"), image.get("description")) if isinstance(image, dict) else (image, "")
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 2048:
            rows.append({"url": url, "description": str(description or "")[:300]})
    return list({row["url"]: row for row in rows}.values())


async def download(item_dir: Path, candidates: list[dict]) -> list[dict]:
    from domains.media.services.remote_image import fetch_remote_image

    item_dir.mkdir(parents=True, exist_ok=True)
    usable = []
    for index, candidate in enumerate(candidates):
        path = item_dir / f"{index}.webp"
        if not path.exists():
            try:
                prepared = await fetch_remote_image(candidate["url"])
            except HTTPException:
                continue
            path.write_bytes(prepared.content)
        with Image.open(path) as image:
            width, height = image.size
        if min(width, height) >= MIN_SIDE and 0.6 <= width / height <= 1.8:
            usable.append({**candidate, "path": str(path), "width": width, "height": height})
    return usable


async def judge_group(client: httpx.AsyncClient, item: dict, group: list[dict]) -> list[dict]:
    content: list = [{"type": "text", "text": PROMPT.format(
        name=item["name_vi"], name_en=item.get("name_en") or "", count=len(group), kind_hint=KIND_HINT[item["kind"]])}]
    for position, candidate in enumerate(group, 1):
        with Image.open(candidate["path"]) as image:
            small = image.convert("RGB")
            small.thumbnail((512, 512))
            buffer = BytesIO()
            small.save(buffer, format="JPEG", quality=85)
        content += [{"type": "text", "text": f"Ảnh {position}:"}, image_part(buffer.getvalue(), "image/jpeg")]
    verdicts = await chat_json(client, MODEL, content, max_tokens=2000)
    by_index = {v.get("index"): v for v in verdicts if isinstance(v, dict)} if isinstance(verdicts, list) else {}
    return [{**candidate, "verdict": by_index.get(position, {}),
             "score": score(by_index.get(position, {}), candidate["width"], candidate["height"])}
            for position, candidate in enumerate(group, 1)]


async def judge(client: httpx.AsyncClient, item: dict, usable: list[dict]) -> list[dict]:
    """Giữ nhóm 4 ảnh để ổn định ngân sách và cách chấm giữa các lần chạy."""
    shown = usable[:MAX_CANDIDATES]
    scored = []
    for start in range(0, len(shown), IMAGES_PER_CALL):
        scored += await judge_group(client, item, shown[start:start + IMAGES_PER_CALL])
    return scored


async def search_one(model_client_http, tavily, item: dict, results: dict) -> None:
    """Thêm ứng viên theo từng nguồn (ảnh OFF, truy vấn tiếng Việt, truy vấn tiếng Anh) tới khi có ảnh đủ tốt."""
    key = item["key"]
    hint = {"dish": "món ăn", "food": "thực phẩm", "product": "sản phẩm"}[item["kind"]]
    sources: list = ([[{"url": item["image_url"], "description": "Open Food Facts front image"}]]
                     if item.get("image_url") else [])
    sources += [f"{item['name_vi']} {hint}"] + ([f"{item['name_en']} food photo"] if item.get("name_en") else [])
    candidates: list[dict] = []
    scored: list[dict] = []
    used = 0
    for source in sources:
        if any((c["score"] or 0) >= GOOD_SCORE for c in scored):
            break
        if isinstance(source, str):
            found = await tavily_images(tavily, source)
            used += 1
        else:
            found = source
        known = {c["url"] for c in candidates}
        candidates += [row for row in found if row["url"] not in known]
        usable = await download(CANDIDATES / safe(key), candidates)
        judged = {c["path"] for c in scored}
        fresh = [c for c in usable if c["path"] not in judged][:MAX_CANDIDATES - len(scored)]
        if fresh:
            scored += await judge(model_client_http, item, fresh)
    results[key] = {"key": key, "name_vi": item["name_vi"], "kind": item["kind"], "tavily_queries": used,
                    "candidates": scored}


def relaxed_score(candidate: dict) -> float | None:
    """Điểm khi bỏ qua tiêu chí chữ: model đánh dấu cả nhãn in trên chai/bao bì (nước mắm, Sting) là chữ chèn."""
    return score({**candidate.get("verdict", {}), "text_or_watermark": False}, candidate["width"], candidate["height"])


def choose(results: dict, overrides: dict) -> dict[str, dict]:
    """Ứng viên được chọn cho mỗi mục: override trước, rồi điểm cao nhất không trùng ảnh với mục khác.

    Mục không còn ảnh đạt nào (hoặc ảnh đạt trùng mục khác) nhận ảnh đúng món chỉ vướng chữ; các mục này xếp sau mọi
    mục có ảnh đạt nên không lấy mất ảnh của mục khác, và cần xem lại ở review.html."""
    chosen, hashes = {}, {}
    for key, result in sorted(results.items(), key=lambda kv: -max((c["score"] or 0) for c in kv[1]["candidates"]) if kv[1]["candidates"] else 0):
        if key in overrides:
            pick = overrides[key]
            if pick is None:
                continue
            if isinstance(pick, int) and pick < len(result["candidates"]):
                chosen[key] = result["candidates"][pick]
                continue
        ranked = sorted((c for c in result["candidates"] if c["score"] is not None), key=lambda c: -c["score"])
        relaxed = sorted((c for c in result["candidates"] if c["score"] is None and relaxed_score(c) is not None),
                         key=lambda c: -relaxed_score(c))
        for candidate in [*ranked, *relaxed]:
            with Image.open(candidate["path"]) as image:
                value = dhash(image)
            if all(bin(value ^ other).count("1") > DUPLICATE_BITS for other in hashes.values()):
                hashes[key] = value
                chosen[key] = candidate
                break
    return chosen


def cropped(key: str, candidate: dict) -> Path:
    path = CROPS / f"{safe(key)}.webp"
    if not path.exists() or path.stat().st_mtime < Path(candidate["path"]).stat().st_mtime:
        CROPS.mkdir(parents=True, exist_ok=True)
        with Image.open(candidate["path"]) as image:
            crop_square(image.convert("RGB"), candidate.get("verdict", {}).get("box")).save(path, "WEBP", quality=85)
    return path


async def search(items_path: Path, limit: int | None, concurrency: int) -> None:
    from agentic.configs.settings import agent_settings

    items = read_json(items_path)
    results = read_json(OUT) if OUT.exists() else {}
    todo = [item for item in items if item["key"] not in results][: limit or None]
    semaphore = asyncio.Semaphore(concurrency)
    tavily_key = agent_settings.TAVILY_API_KEY.get_secret_value()

    async def one(model_client_http, tavily, item):
        async with semaphore:
            try:
                await search_one(model_client_http, tavily, item, results)
            except Exception as exc:  # một mục lỗi không dừng cả lượt; chạy lại sẽ thử tiếp
                print(f"{item['key']}: {type(exc).__name__}: {exc}"[:200])

    async with model_client() as model_client_http, httpx.AsyncClient(headers={"Authorization": f"Bearer {tavily_key}"}) as tavily:
        await asyncio.gather(*(one(model_client_http, tavily, item) for item in todo))
    write_json(OUT, results)
    chosen = choose({key: results[key] for key in (item["key"] for item in todo) if key in results}, {})
    queries = sum(results[item["key"]]["tavily_queries"] for item in todo if item["key"] in results)
    print(f"{len(todo)} items searched, {queries} Tavily queries, {len(chosen)} with a usable image -> {OUT}")


def review() -> Path:
    results = read_json(OUT)
    overrides = read_json(OVERRIDES) if OVERRIDES.exists() else {}
    chosen = choose(results, overrides)
    rows = []
    for key, result in sorted(results.items(), key=lambda kv: kv[1]["name_vi"]):
        pick = chosen.get(key)
        main = (f'<img src="{cropped(key, pick).as_uri()}">' if pick else '<div class="none">không có ảnh</div>')
        alts = "".join(
            f'<figure class="{"on" if pick and c["path"] == pick["path"] else ""}"><img src="{Path(c["path"]).as_uri()}">'
            f'<figcaption>#{i} · {c["score"] if c["score"] is not None else "loại"}</figcaption></figure>'
            for i, c in enumerate(result["candidates"]))
        rows.append(f'<section><h2>{html.escape(result["name_vi"])} <small>{html.escape(key)}</small></h2>'
                    f'<div class="row"><div class="main">{main}</div><div class="alts">{alts}</div></div></section>')
    page = CACHE / "review.html"
    page.write_text(
        "<!doctype html><meta charset=utf-8><title>Duyệt ảnh catalog</title><style>"
        "body{font:14px system-ui;margin:16px;background:#fafafa}section{border-bottom:1px solid #ddd;padding:8px 0}"
        "h2{font-size:15px;margin:4px 0}small{color:#888;font-weight:400}.row{display:flex;gap:12px}"
        ".main img,.none{width:200px;height:200px;object-fit:cover;border-radius:8px}.none{background:#eee;display:grid;place-items:center}"
        ".alts{display:flex;flex-wrap:wrap;gap:6px}figure{margin:0}figure img{width:110px;height:110px;object-fit:cover;border-radius:6px}"
        "figure.on img{outline:3px solid #2a7}figcaption{font-size:11px;color:#555;text-align:center}</style>"
        f"<p>{len(chosen)}/{len(results)} mục có ảnh. Đổi lựa chọn trong scripts/catalog/image_overrides.json.</p>"
        + "".join(rows), encoding="utf-8")
    print(f"{len(chosen)}/{len(results)} items with an image -> {page}")
    return page


async def upload() -> None:
    from core.settings import settings
    from domains.media.services.cloudinary_images import CloudinaryImages, prepare_image

    results = read_json(OUT)
    overrides = read_json(OVERRIDES) if OVERRIDES.exists() else {}
    uploaded_path = CACHE / "uploaded.json"
    uploaded = read_json(uploaded_path) if uploaded_path.exists() else {}
    cloud = CloudinaryImages()
    for key, candidate in choose(results, overrides).items():
        prepared = prepare_image(cropped(key, candidate).read_bytes())
        public_id = f"{settings.CLOUDINARY_FOLDER}/foods/catalog/{hashlib.sha1(prepared.content).hexdigest()}"
        if uploaded.get(key, {}).get("public_id") == public_id:
            continue
        url = await cloud.upload(prepared, public_id)
        uploaded[key] = {"public_id": public_id, "url": url, "source_url": candidate["url"]}
        write_json(uploaded_path, uploaded)
    print(f"{len(uploaded)} images on Cloudinary -> {uploaded_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    se = sub.add_parser("search")
    se.add_argument("--items", type=Path, required=True)
    se.add_argument("--limit", type=int)
    se.add_argument("--concurrency", type=int, default=3)
    sub.add_parser("review")
    sub.add_parser("upload")
    args = parser.parse_args()
    if args.command == "search":
        asyncio.run(search(args.items, args.limit, args.concurrency))
    elif args.command == "review":
        review()
    else:
        asyncio.run(upload())
