# Adding / changing a downloader

* Every site not listed below goes through **yt-dlp** (1000+ sites): `lysandra/extractors/ytdlp.py`.
* **YouTube**: `youtube.py` (proxy rotation + cookies + relay).
* **TeraBox family**: `terabox.py` needs an upstream resolver. Set `TERABOX_API_URL`; the server calls
  `GET <TERABOX_API_URL>?url=<terabox link>` and expects JSON
  `{"title": "...", "thumbnail": "...", "download_url": "https://...", "size": 123456, "ext": "mp4", "duration": 60}`.
  Until it is configured the app shows "TeraBox downloads are not enabled on the server yet." (no fake data).
* **New site with custom logic**: create `lysandra/extractors/mysite.py`:
  ```python
  from .base import Extractor, ExtractorError
  class MySite(Extractor):
      name = "mysite"; domains = ("mysite.com",)
      def extract(self, url):
          ...   # return {"title","thumbnail","duration","platform","uploader","relay":False,"formats":[{fid,label,quality,ext,mime,size,url,headers,audio_only,height}]}
  ```
  and add `MySite(ctx)` to the list in `build_registry()` in `base.py`.
* Only progressive (video+audio in one file) http(s) formats and one audio-only format are offered: the app has no ffmpeg.
