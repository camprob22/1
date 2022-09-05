from .common import InfoExtractor
from ..utils import parse_iso8601


class PrankCastIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?prankcast\.com/.*/showreel/(?P<id>\d+)-(?P<display_id>.+)'
    _TESTS = [{
        'url': 'https://prankcast.com/Devonanustart/showreel/1561-Beverly-is-back-like-a-heart-attack-',
        'info_dict': {
            'id': '1561',
            'ext': 'mp3',
            'title': 'Beverly is back like a heart attack!',
            'uploader': 'Devonanustart',
            'upload_date': '20220825'
        }
    }]

    def _real_extract(self, url):
        video_id, display_id = self._match_valid_url(url).group('id', 'display_id')

        webpage = self._download_webpage(url, video_id)

        # Extract the JSON
        json_info = self._search_nextjs_data(webpage, video_id)['props']['pageProps']['ssr_data_showreel']

        # Get author (AKA show host)
        uploader = json_info.get('user_name')

        # Get the co-hosts/guests
        guests_json = self._parse_json(json_info.get('guests_json') or '{}', video_id)
        guests = [] if not uploader else [uploader] + [x.get('name') for x in guests_json if x.get('name') is not None]

        # Get dates
        start_date = parse_iso8601(json_info.get('start_date'))
        end_date = parse_iso8601(json_info.get('end_date'))

        # Parse the duration of the stream
        parsed_duration = None
        if start_date is not None and end_date is not None:
            parsed_duration = (end_date - start_date)

        return {
            'id': video_id,
            'title': json_info.get('broadcast_title') or self._og_search_title(webpage),
            'display_id': display_id,
            'url': f'{json_info["broadcast_url"]}{json_info["recording_hash"]}.mp3',
            'timestamp': start_date,
            'uploader': uploader,
            'channel_id': json_info.get('user_id'),
            'duration': parsed_duration,
            'cast': guests,
            'description': json_info.get('broadcast_description'),
            'categories': [json_info.get('broadcast_category')],
            'tags': self._parse_json(json_info.get('broadcast_tags'), video_id)
        }
