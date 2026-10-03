"""FFmpeg helpers: prepare inputs, probe, frames, demo clips."""
from __future__ import annotations
import json
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

W, H, FPS = 1080, 1920, 30


class MediaError(RuntimeError):
    pass


def run(cmd, timeout=600):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if r.returncode != 0:
        tail = r.stderr.decode("utf-8", "ignore")[-1500:]
        raise MediaError(f"Команда не сработала: {' '.join(map(str, cmd[:6]))}…\n{tail}")
    return r.stdout.decode("utf-8", "ignore")


def check_tools():
    return {"ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")),
            "sips": bool(shutil.which("sips")), "encoder": video_encoder() if shutil.which("ffmpeg") else None}


@lru_cache(maxsize=1)
def video_encoder():
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL).stdout.decode("utf-8", "ignore")
    if " libx264 " in out:
        return "libx264"
    if "h264_videotoolbox" in out:
        return "h264_videotoolbox"
    return "mpeg4"


def venc_args():
    e = video_encoder()
    if e == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p"]
    if e == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p"]
    return ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]


def probe(path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    j = json.loads(out)
    dur = float(j.get("format", {}).get("duration") or 0)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    vdur = float(v.get("duration") or 0) or dur
    return {"duration": dur, "video_duration": vdur, "width": v.get("width"), "height": v.get("height"),
            "has_audio": any(s.get("codec_type") == "audio" for s in j.get("streams", []))}


def fit_filter(mode: str = "crop", w: int = W, h: int = H, src: str = "0:v", out: str = "vfit") -> str:
    """Фрагмент filter_complex: привести кадр к w×h.
    crop — заполнить и обрезать края; blur — вписать целиком на размытый фон того же кадра."""
    if mode == "blur":
        return (f"[{src}]split=2[bg_{out}][fg_{out}];"
                f"[bg_{out}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=28:2,eq=brightness=-0.06[bb_{out}];"
                f"[fg_{out}]scale={w}:{h}:force_original_aspect_ratio=decrease[ff_{out}];"
                f"[bb_{out}][ff_{out}]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]")
    return f"[{src}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[{out}]"


def vertical_blur_image(src: Path, dst: Path, w: int = 1152, h: int = 2048) -> Path:
    """Фото → вертикальный кадр 9:16: фото целиком по центру на размытом фоне из него же (бесплатно)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", fit_filter("blur", w, h, "0:v", "v"),
         "-map", "[v]", "-frames:v", "1", "-q:v", "2", str(dst)])
    return dst


def prepare_photo(src: Path, dst: Path, max_side=2048) -> Path:
    """Any photo (incl. iPhone HEIC on Mac) → JPEG, longest side ≤ max_side."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin" and shutil.which("sips"):
        run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92", "-Z", str(max_side), str(src), "--out", str(dst)])
    else:
        run(["ffmpeg", "-y", "-i", str(src), "-vf",
             f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'",
             "-q:v", "2", str(dst)])
    return dst


def prepare_video(src: Path, dst: Path, seconds=5.0) -> Path:
    """Trim to `seconds` (Kling edit bills per second of input), drop audio, keep resolution."""
    info = probe(src)
    t = min(seconds, info["duration"] or seconds)
    if t < 3:
        raise MediaError("Видео слишком короткое: нужно минимум 3 секунды.")
    run(["ffmpeg", "-y", "-i", str(src), "-t", f"{t:.2f}", "-an",
         "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30", *venc_args(), str(dst)])
    return dst


def extract_frames(video: Path, out_dir: Path, n=3, width=720):
    out_dir.mkdir(parents=True, exist_ok=True)
    d = probe(video)["duration"] or 1
    frames = []
    for i in range(n):
        t = d * (i + 0.5) / n
        f = out_dir / f"{video.stem}_f{i+1}.jpg"
        run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", f"scale={width}:-2", "-q:v", "3", str(f)])
        frames.append(f)
    return frames


def best_frames_from_video(video: Path, out_dir: Path, n=6):
    """Реставратор-lite: берём n равномерно распределённых кадров из видео сборщика."""
    return extract_frames(video, out_dir, n=n, width=1280)


def demo_clip_from_photo(photo: Path, out: Path, seconds=5.0, zoom_in=True):
    """Бесплатная замена генерации: медленный наезд на фото (эффект Кена Бёрнса)."""
    frames = int(seconds * FPS)
    z = "min(zoom+0.0012,1.25)" if zoom_in else "if(eq(on,0),1.25,max(zoom-0.0012,1.0))"
    vf = (f"scale={W*4//3}:{H*4//3}:force_original_aspect_ratio=increase,crop={W*4//3}:{H*4//3},"
          f"zoompan=z='{z}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(photo), "-vf", vf, "-t", f"{seconds}", *venc_args(), str(out)])
    return out


def demo_clip_from_video(video: Path, out: Path, seconds=5.0):
    """Демо для «видео в видео»: берём видео сборщика и подкрашиваем в тёплый тон."""
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
          "eq=contrast=1.06:saturation=1.12:brightness=0.02,colorbalance=rs=0.04:gs=0.01:bs=-0.04,format=yuv420p")
    run(["ffmpeg", "-y", "-i", str(video), "-t", f"{seconds}", "-an", "-vf", vf, *venc_args(), str(out)])
    return out


def thumbnail(video: Path, out: Path):
    d = probe(video)["duration"] or 1
    run(["ffmpeg", "-y", "-ss", f"{min(1.0, d/2):.2f}", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=360:-2", "-q:v", "4", str(out)])
    return out
