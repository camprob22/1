import base64
import json
import re
import urllib.parse

from .common import InfoExtractor
from ..utils import ExtractorError, determine_ext, join_nonempty, js_to_json


def decode_b64_url(code):
    decoded_url = re.match(r'[^[]*\[([^]]*)\]', code).groups()[0]
    return base64.b64decode(
        urllib.parse.unquote(re.sub(r'[\s"\',]', '', decoded_url)),
    ).decode('utf-8')


class RTPIE(InfoExtractor):
    _VALID_URL = r'https?://(?:(?:(?:www\.)?rtp\.pt/play/(?P<subarea>.*/)?p(?P<program_id>[0-9]+)/(?P<episode_id>e[0-9]+/)?)|(?:arquivos\.rtp\.pt/conteudos/))(?P<id>[^/?#]+)/?'
    _TESTS = [{
        'url': 'https://www.rtp.pt/play/p9165/e562949/por-do-sol',
        'info_dict': {
            'id': 'por-do-sol',
            'ext': 'mp4',
            'title': 'Pôr do Sol Episódio 1 - de 16 Ago 2021',
            'description': 'Madalena Bourbon de Linhaça vive atormentada pelo segredo que esconde desde 1990. Matilde Bourbon de Linhaça sonha fugir com o seu amor proibido. O en',
            'thumbnail': r're:^https?://.*\.jpg',
        },
    }, {
        'url': 'https://www.rtp.pt/play/p510/aleixo-fm',
        'only_matching': True,
    }]

    _RX_OBFUSCATION = re.compile(r'''(?xs)
        atob\s*\(\s*decodeURIComponent\s*\(\s*
            (\[[0-9A-Za-z%,'"]*\])
        \s*\.\s*join\(\s*(?:""|'')\s*\)\s*\)\s*\)
    ''')

    def __unobfuscate(self, data, *, video_id):
        if data.startswith('{'):
            data = self._RX_OBFUSCATION.sub(
                lambda m: json.dumps(
                    base64.b64decode(urllib.parse.unquote(
                        ''.join(self._parse_json(m.group(1), video_id)),
                    )).decode('iso-8859-1')),
                data)
        return js_to_json(data)

    def _real_extract(self, url):
        video_id = self._match_id(url)

        webpage = self._download_webpage(url, video_id)

        # Remove comments from webpage source
        webpage = re.sub(r'(?s)/\*.*\*/', '', webpage)
        webpage = re.sub(r'(?m)(?:^|\s)//.*$', '', webpage)

        title = self._html_search_regex(r'<title>(.+?)</title>', webpage, 'title', default='')
        # Replace irrelevant text in title
        title = title.replace(' - RTP Play - RTP', '') or self._html_search_meta('twitter:title', webpage)

        if 'Este episódio não se encontra disponí' in title:
            raise ExtractorError('Episode unavailable', expected=True)

        part = self._html_search_regex(r'section\-parts.*<span.*>(.+?)</span>.*</ul>', webpage, 'part', default=None)
        title = join_nonempty(title, part, delim=' ')

        # Get JS object
        js_object = self._search_regex(r'(?s)RTPPlayer *\( *({.+?}) *\);', webpage, 'player config')
        json_string_for_config = ''
        full_url = None

        # Verify JS object since it isn't pure JSON and maybe it needs some tuning
        for line in js_object.splitlines():
            stripped_line = line.strip()

            # key == 'fileKey', then we found what we wanted
            if re.match(r'fileKey:', stripped_line):
                if re.match(r'fileKey: *""', stripped_line):
                    raise ExtractorError('Episode not found (probably removed)', expected=True)
                url = decode_b64_url(stripped_line)
                if 'mp3' in url:
                    full_url = 'https://cdn-ondemand.rtp.pt' + url
                else:
                    full_url = f'https://streaming-vod.rtp.pt/dash{url}/manifest.mpd'

            elif not stripped_line.startswith('//') and not re.match('file *:', stripped_line) and not re.match('.*extraSettings ?:', stripped_line):
                # Ignore commented lines, `extraSettings` and `f`. The latter seems to some random unrelated video.
                json_string_for_config += '\n' + line

        if not full_url:
            raise ExtractorError('No valid media source found in page')

        # Finally send pure JSON string for JSON parsing
        config = self._parse_json(json_string_for_config, video_id, js_to_json)
        full_url = full_url.replace('drm-dash', 'dash')
        ext = determine_ext(full_url)

        if ext == 'mpd':
            # Download via mpd file
            formats = self._extract_mpd_formats(full_url, video_id)
        else:
            formats = [{
                'url': full_url,
                'ext': ext,
            }]

        subtitles = {}

        vtt = config.get('vtt')
        if vtt is not None:
            for lcode, lname, url in vtt:
                subtitles.setdefault(lcode, []).append({
                    'name': lname,
                    'url': url,
                })

        return {
            'id': video_id,
            'title': title,
            'formats': formats,
            'description': self._html_search_meta(['description', 'twitter:description'], webpage),
            'thumbnail': config.get('poster') or self._og_search_thumbnail(webpage),
            'subtitles': subtitles,
        }
