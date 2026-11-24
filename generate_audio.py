"""Generate the GitHub Pages essay audio from source.txt (pip install edge-tts)."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parent
TITLE = re.compile(r"第[一二三四五六七八九十百0-9]+篇[:：]")
CHINESE = re.compile(r"[\u3400-\u9fff]")


def is_english(line):
    return bool(re.search(r"[A-Za-z]{2}", line)) and not CHINESE.search(line)


def clean(line):
    return re.sub(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", line).strip()


def tracks(source):
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    essays = []
    mode = None
    for index, line in enumerate(lines):
        if TITLE.search(line):
            essays.append(([], []))
            mode = None
        elif "中英逐句对照版" in line:
            mode = "pairs"
        elif "完整纯英文版" in line:
            mode = "full"
        elif "完整中文版" in line:
            mode = None
        elif essays and is_english(line):
            pairs, full = essays[-1]
            if mode == "pairs" and index + 1 < len(lines) and CHINESE.search(lines[index + 1]):
                pairs.append(clean(line))
            elif mode == "full":
                full.append(clean(line))
    valid = [(pairs, full) for pairs, full in essays if pairs or full]
    for essay, (pairs, full) in enumerate(valid, 1):
        for sentence, text in enumerate(pairs, 1):
            yield f"e{essay}_s{sentence}", text
        yield f"e{essay}_full", "\n\n".join(full or pairs)


def write_manifest(folder, manifest):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as temp:
        temp_path = Path(temp.name)
        json.dump(manifest, temp, ensure_ascii=False, indent=2)
        temp.write("\n")
    temp_path.replace(folder / "manifest.json")


async def generate(args, entries):
    import edge_tts

    folder = ROOT / "audio"
    folder.mkdir(exist_ok=True)
    manifest_path = folder / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest = {}
    semaphore = asyncio.Semaphore(3)

    async def generate_track(key, text):
        fingerprint = hashlib.sha256(f"{args.voice}\0{args.rate}\0{text}".encode()).hexdigest()
        filename = f"{key}.{fingerprint[:12]}.mp3"
        target = folder / filename
        if previous.get(key, {}).get("file") == filename and target.exists() and target.stat().st_size:
            manifest[key] = {"file": filename, "text": text}
            return True
        async with semaphore:
            for attempt in range(3):
                with tempfile.NamedTemporaryFile(suffix=".mp3", dir=folder, delete=False) as temp:
                    temp_path = Path(temp.name)
                try:
                    await asyncio.wait_for(
                        edge_tts.Communicate(text, args.voice, rate=args.rate).save(str(temp_path)),
                        timeout=35,
                    )
                    if not temp_path.stat().st_size:
                        raise ValueError("空音频")
                    temp_path.replace(target)
                    manifest[key] = {"file": filename, "text": text}
                    print(f"已生成 {key}", flush=True)
                    return True
                except Exception as error:
                    if attempt == 2:
                        print(f"失败 {key}: {error!r}", flush=True)
                    else:
                        await asyncio.sleep(2 ** attempt)
                finally:
                    temp_path.unlink(missing_ok=True)
        return False

    results = await asyncio.gather(*(generate_track(key, text) for key, text in entries))
    write_manifest(folder, {key: manifest[key] for key, _ in entries if key in manifest})
    print(f"可用音频 {sum(results)}/{len(entries)}", flush=True)
    return 0 if all(results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="en-US-AndrewNeural")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--list", action="store_true", help="Print track IDs and texts without generating")
    args = parser.parse_args()
    entries = list(tracks((ROOT / "source.txt").read_text(encoding="utf-8-sig")))
    if not entries:
        parser.error("source.txt 中没有可朗读的范文")
    if args.list:
        print(json.dumps(dict(entries), ensure_ascii=False))
        return 0
    return asyncio.run(generate(args, entries))


if __name__ == "__main__":
    raise SystemExit(main())
