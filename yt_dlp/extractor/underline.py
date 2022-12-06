from .common import InfoExtractor

DEBUG_P = False
if DEBUG_P:
    import json
    from icecream import ic
    from IPython import embed


def gen_dict_extract(var, key):
    if hasattr(var, "items"):
        for k, v in var.items():
            if k == key:
                yield v
            if isinstance(v, dict):
                for result in gen_dict_extract(v, key):
                    yield result
            elif isinstance(v, list):
                for d in v:
                    for result in gen_dict_extract(d, key):
                        yield result


class UnderlineIE(InfoExtractor):
    _VALID_URL = r"https?://(?:www\.)?underline\.io/events/(?P<id>[^?]+).*"

    _TESTS = [
        {
            "params": {
                "skip_download": True,  # needs cookies
            },
            "url": "https://underline.io/events/342/posters/12863/poster/66463-mbti-personality-prediction-approach-on-persian-twitter?tab=video",
            "md5": "md5:eaa894161adaef6efd6008681e1cd2c5",
            # md5 sum of the first 10241 bytes of the video file (use --test)
            "info_dict": {
                "id": "342/posters/12863/poster/66463-mbti-personality-prediction-approach-on-persian-twitter",
                "ext": "mp4",
                "title": "MBTI Personality Prediction Approach on Persian Twitter",
            },
        }
    ]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        webpage_info = self._search_json(
            r'<script\s+id="__NEXT_DATA__"\s+type="application/json">',
            webpage,
            "idk_what_this_arg_does",
            video_id,
            end_pattern=r"</script>",
        )

        if DEBUG_P:
            with open("./tmp.json", "w") as f:
                json.dump(webpage_info, f)

        title = list(gen_dict_extract(webpage_info, "title"))
        if DEBUG_P:
            ic(title)

        if len(title) == 0:
            title = None
        else:
            title = title[0]

        playlist_urls = list(gen_dict_extract(webpage_info, "playlist"))
        if DEBUG_P:
            ic(playlist_urls)

        if len(playlist_urls) == 0:
            url = None
        else:
            url = playlist_urls[0]

        formats = []

        m3u8_url = url
        if m3u8_url:
            formats.extend(
                self._extract_m3u8_formats(
                    m3u8_url, video_id, ext="mp4", entry_protocol="m3u8_native"
                )
            )

        return {
            "id": video_id,
            "title": title,
            "formats": formats,
        }
