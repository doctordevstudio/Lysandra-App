"""Turns a yt-dlp info dict into the three format tabs the app shows:
Audio+Video (progressive, HLS and *auto-merge* pairs), Video only and Audio only."""
MIME = {"mp4": "video/mp4", "webm": "video/webm", "m4a": "audio/mp4", "mp3": "audio/mpeg", "mov": "video/quicktime",
        "3gp": "video/3gpp", "mkv": "video/x-matroska", "aac": "audio/aac", "ogg": "audio/ogg", "opus": "audio/opus",
        "m4v": "video/mp4", "flv": "video/x-flv", "ts": "video/mp2t", "wav": "audio/wav", "flac": "audio/flac"}
OK_EXT = set(MIME)
MERGE_VCODECS = ("avc1", "h264", "hev1", "hvc1", "hevc")      # what Android's MediaMuxer can put in an mp4 without re-encoding
MERGE_ACODECS = ("mp4a", "aac")


def _size(f, duration):
    s = f.get("filesize") or f.get("filesize_approx")
    if s:
        return int(s), False
    tbr = f.get("tbr") or ((f.get("vbr") or 0) + (f.get("abr") or 0))
    if tbr and duration:
        return int(tbr * 125 * duration), True
    return 0, False


def _short(codec):
    return (codec or "").split(".")[0] if codec and codec != "none" else ""


def _quality(f):
    h = int(f.get("height") or 0)
    if not h:
        return f.get("format_note") or "Video"
    fps = int(f.get("fps") or 0)
    return f"{h}p{fps if fps > 30 else ''}"


def build_formats(info):
    duration = int(info.get("duration") or 0)
    raw = []
    for f in info.get("formats") or []:
        url, proto, ext = f.get("url"), f.get("protocol") or "", (f.get("ext") or "").lower()
        if not url or ext in ("mhtml", "") or proto not in ("https", "http", "m3u8", "m3u8_native"):
            continue
        hls = proto.startswith("m3u8")
        if not hls and ext not in OK_EXT:
            continue
        vc, ac = f.get("vcodec"), f.get("acodec")
        has_v, has_a = vc not in (None, "none"), ac not in (None, "none")
        if not has_v and not has_a:
            if hls and vc is None and ac is None:      # codecs unknown in HLS -> muxed stream
                has_v = has_a = True
            else:
                continue
        size, approx = _size(f, duration)
        raw.append({"f": f, "hls": hls, "ext": "mp4" if hls else ext, "v": has_v, "a": has_a, "size": size, "approx": approx})

    def make(r, kind):
        f = r["f"]
        h = int(f.get("height") or 0)
        q = _quality(f) if r["v"] else f"{int(f.get('abr') or f.get('tbr') or 0)}kbps" if (f.get("abr") or f.get("tbr")) else "Audio"
        label = {"av": f"{q} {'HLS' if r['hls'] else r['ext'].upper()}", "video": f"{q} {r['ext'].upper()} (no sound)", "audio": f"Audio {r['ext'].upper()} {q}"}[kind]
        return {"fid": f"{'v' if kind == 'video' else 'a' if kind == 'audio' else 'f'}{f.get('format_id')}", "kind": kind, "label": label,
                "quality": q, "ext": r["ext"], "mime": MIME.get(r["ext"], "video/mp4"), "size": r["size"], "size_approx": r["approx"],
                "url": f["url"], "headers": f.get("http_headers") or {}, "audio_only": kind == "audio", "video_only": kind == "video",
                "height": h, "fps": int(f.get("fps") or 0), "vcodec": _short(f.get("vcodec")), "acodec": _short(f.get("acodec")),
                "hls": r["hls"], "duration": duration, "tbr": int(f.get("tbr") or 0)}

    def best(rows, key):
        rows = sorted(rows, key=lambda r: (r["size"], r["f"].get("tbr") or 0), reverse=True)
        seen, out = set(), []
        for r in rows:
            k = key(r)
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out

    av = best([r for r in raw if r["v"] and r["a"]], lambda r: (int(r["f"].get("height") or 0), r["ext"], r["hls"]))
    vo = best([r for r in raw if r["v"] and not r["a"] and not r["hls"]], lambda r: (int(r["f"].get("height") or 0), r["ext"]))
    ao = best([r for r in raw if r["a"] and not r["v"] and not r["hls"]], lambda r: (r["ext"], int((r["f"].get("abr") or r["f"].get("tbr") or 0) // 64)))
    av.sort(key=lambda r: int(r["f"].get("height") or 0), reverse=True)
    vo.sort(key=lambda r: (int(r["f"].get("height") or 0), r["size"]), reverse=True)
    ao.sort(key=lambda r: (r["f"].get("abr") or r["f"].get("tbr") or 0), reverse=True)
    out = [make(r, "av") for r in av[:8]] + [make(r, "video") for r in vo[:8]] + [make(r, "audio") for r in ao[:4]]

    # ---- auto merge: video-only mp4 heights that have no ready-made audio+video file, paired with the best m4a
    have_av = {x["height"] for x in out if x["kind"] == "av"}
    m4a = next((x for x in out if x["kind"] == "audio" and x["ext"] == "m4a" and x["acodec"] in MERGE_ACODECS), None)
    merges = []
    if m4a:
        for x in out:
            if x["kind"] == "video" and x["ext"] == "mp4" and x["vcodec"] in MERGE_VCODECS and x["height"] and x["height"] not in have_av:
                merges.append({"fid": f"m{x['fid'][1:]}+{m4a['fid'][1:]}", "kind": "merge", "label": f"{x['quality']} MP4 · Auto merge video + audio",
                               "quality": x["quality"], "ext": "mp4", "mime": "video/mp4", "size": x["size"] + m4a["size"],
                               "size_approx": x["size_approx"] or m4a["size_approx"], "audio_only": False, "video_only": False,
                               "height": x["height"], "fps": x["fps"], "vcodec": x["vcodec"], "acodec": m4a["acodec"], "hls": False,
                               "duration": duration, "tbr": x["tbr"], "parts": [x["fid"], m4a["fid"]], "headers": {}, "url": ""})
                have_av.add(x["height"])
    merges.sort(key=lambda m: m["height"], reverse=True)
    # merge items belong to the Audio+Video tab, after the ready-made files
    final = [x for x in out if x["kind"] == "av"] + merges + [x for x in out if x["kind"] != "av"]
    return final
