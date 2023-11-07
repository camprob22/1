from .common import InfoExtractor
from ..utils import (
    join_nonempty,
    traverse_obj,
    unified_timestamp,
)


class DuoplayIE(InfoExtractor):
    _VALID_URL = r'https://duoplay\.ee/(?P<id>\d+)/'
    _TESTS = [{
        'note': 'Siberi võmm S02E12',
        'url': 'https://duoplay.ee/4312/siberi-vomm?ep=24',
        'md5': '1ff59d535310ac9c5cf5f287d8f91b2d',
        'info_dict': {
            'id': '4312',
            'ext': 'mp4',
            'title': 'Siberi võmm - S02E12 - Operatsioon "Öö"',
            'thumbnail': r're:https://.+\.jpg(?:\?c=\d+)?$',
            'description': 'md5:8ef98f38569d6b8b78f3d350ccc6ade8',
            'upload_date': '20170523',
            'timestamp': 1495567800,
        },
    }]

    def _real_extract(self, url):
        def decode_quot(s: str):
            return s.replace("&quot;", '"')

        # Format as "SXXEXX"
        def season_episode(o):
            return 'S%02dE%02d' % (
                traverse_obj(o, 'season_id'),
                traverse_obj(0, 'episode_nr'),
            )

        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)
        manifest_url = self._search_regex(r'<video-player[^>]+manifest-url="([^"]+)"', webpage, 'video-player')
        episode_attr = self._search_regex(r'<video-player[^>]+:episode="([^"]+)"', webpage, 'episode data')
        ep = self._parse_json(episode_attr, video_id, decode_quot)

        return {
            'id': video_id,
            'title': join_nonempty(traverse_obj(ep, 'title'), season_episode(ep), traverse_obj(ep, 'subtitle'), delim=' - '),
            'description': traverse_obj(ep, 'synopsis'),
            'thumbnail': traverse_obj(ep, ('images', 'original')),
            'formats': self._extract_m3u8_formats(manifest_url, video_id, 'mp4'),
            'timestamp': unified_timestamp(traverse_obj(ep, 'airtime') + ' +0200'),
        }