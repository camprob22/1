import time
import hashlib
import re
import urllib
import uuid

from .common import InfoExtractor
from .openload import PhantomJSwrapper
from ..utils import (
    UserNotLive,
    int_or_none,
    str_or_none,
    url_or_none,
    traverse_obj,
    determine_ext,
    parse_resolution,
    urlencode_postdata,
    unescapeHTML,
    urljoin,
)


class DouyuBaseIE(InfoExtractor):
    def _get_cryptojs_md5(self, video_id):
        return self._download_webpage(
            'https://cdnjs.cloudflare.com/ajax/libs/crypto-js/3.1.2/rollups/md5.js', video_id,
            note='Downloading signing dependency')

    def _calc_sign(self, sign_func, a, b, c, video_id):
        js_script = self._get_cryptojs_md5(video_id) + f';{sign_func};console.log(ub98484234("{a}","{b}","{c}"))'
        phantom = PhantomJSwrapper(self)
        result = phantom.execute(js_script, video_id,
                                 note='Executing JS signing script').strip()
        return {i: v[0] for i, v in urllib.parse.parse_qs(result).items()}


class DouyuTVIE(DouyuBaseIE):
    IE_DESC = '斗鱼'
    _VALID_URL = r'https?://(?:www\.)?douyu(?:tv)?\.com/(topic/\w+\?rid=|(?:[^/]+/))*(?P<id>[A-Za-z0-9]+)'
    _TESTS = [{
        'url': 'https://www.douyu.com/pigff',
        'info_dict': {
            'id': '24422',
            'display_id': 'pigff',
            'ext': 'ts',
            'title': 're:^【PIGFF】.* [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$',
            'description': r'≥15级牌子看鱼吧置顶帖进粉丝vx群',
            'thumbnail': str,
            'uploader': 'pigff',
            'is_live': True,
            'live_status': 'is_live',
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'http://www.douyutv.com/85982',
        'info_dict': {
            'id': '85982',
            'display_id': '85982',
            'ext': 'flv',
            'title': 're:^小漠从零单排记！——CSOL2躲猫猫 [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$',
            'description': 'md5:746a2f7a253966a06755a912f0acc0d2',
            'thumbnail': r're:^https?://.*\.png',
            'uploader': 'douyu小漠',
            'is_live': True,
        },
        'params': {
            'skip_download': True,
        },
        'skip': 'Room not found',
    }, {
        'url': 'http://www.douyutv.com/17732',
        'info_dict': {
            'id': '17732',
            'display_id': '17732',
            'ext': 'flv',
            'title': 're:^清晨醒脑！根本停不下来！ [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$',
            'description': r're:.*m7show@163\.com.*',
            'thumbnail': r're:^https?://.*\.png',
            'uploader': '7师傅',
            'is_live': True,
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'https://www.douyu.com/topic/ydxc?rid=6560603',
        'info_dict': {
            'id': '6560603',
            'display_id': '6560603',
            'ext': 'flv',
            'title': 're:^阿余：新年快乐恭喜发财！ [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$',
            'description': 're:.*直播时间.*',
            'thumbnail': r're:^https?://.*\.png',
            'uploader': '阿涛皎月Carry',
            'live_status': 'is_live',
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'http://www.douyu.com/xiaocang',
        'only_matching': True,
    }, {
        # \"room_id\"
        'url': 'http://www.douyu.com/t/lpl',
        'only_matching': True,
    }]

    def _sign(self, room_id, video_id, params={}):
        params = {
            'tt': round(time.time()),
            'did': uuid.uuid4().hex,
        }
        params.update(self._get_sign(room_id, params['did'], params['tt'], video_id))
        return params

    def _get_sign_func(self, room_id, video_id):
        return self._download_json(
            f'https://www.douyu.com/swf_api/homeH5Enc?rids={room_id}', video_id,
            note='Getting signing script')['data'][f'room{room_id}']

    def _get_sign(self, room_id, nonce, ts, video_id):
        sign_func = self._get_sign_func(room_id, video_id)
        return self._calc_sign(sign_func, room_id, nonce, ts, video_id)

    def _extract_stream_format(self, stream_info):
        rtmp_url = traverse_obj(stream_info, ('data', 'rtmp_url'))
        rtmp_live = traverse_obj(stream_info, ('data', 'rtmp_live'))
        if rtmp_url and rtmp_live:
            stream_url = urljoin(rtmp_url, rtmp_live)
            rate_id = traverse_obj(stream_info, ('data', 'rate'))
            rate_info = traverse_obj(stream_info, ('data', 'multirates', {lambda _, v: v.get('rate') == rate_id}, 0))
            m3u8_extra = {'ext': 'ts', 'protocol': 'm3u8_native'} if '.m3u8' in stream_url else {}
            return {
                'url': stream_url,
                'format_id': str(rate_id),
                'quality': -rate_id,
                **traverse_obj(rate_info, {
                    'format': ('name', {str_or_none}),
                    'tbr': ('bit', {int_or_none}),
                }),
                **m3u8_extra,
            }

    def _real_extract(self, url):
        video_id = self._match_id(url)

        page = self._download_webpage(url, video_id)
        room_id = self._html_search_regex(
            r'(?:\$ROOM\.room_id\s*=|room_id\\?"\s*:)\s*(\d+)[,;]', page, 'room id')

        if '"videoLoop":1,' in page:
            raise UserNotLive('The channel is auto-playing VODs', video_id=video_id)
        if '$ROOM.show_status =2;' in page:
            raise UserNotLive(video_id=video_id)

        # Grab metadata from API
        params = {
            'aid': 'wp',
            'client_sys': 'wp',
            'time': int(time.time()),
        }
        params['auth'] = hashlib.md5(
            f'room/{room_id}?{urllib.parse.urlencode(params)}zNzMV1y4EMxOHS6I5WKm'.encode()).hexdigest()
        room = self._download_json(
            f'http://www.douyutv.com/api/v1/room/{room_id}', video_id,
            note='Downloading room info', query=params)['data']

        # 1 = live, 2 = offline
        if room.get('show_status') == '2':
            raise UserNotLive(video_id=video_id)

        formats = []

        form_data = self._sign(room_id, video_id, {'rate': 0})
        stream_info = self._download_json(
            f'https://www.douyu.com/lapi/live/getH5Play/{room_id}',
            video_id, note="Downloading livestream format",
            data=urlencode_postdata(form_data))
        formats.append(self._extract_stream_format(stream_info))

        for rate_id in traverse_obj(stream_info, ('data', 'multirates', ..., 'rate')):
            if rate_id != traverse_obj(stream_info, ('data', 'rate')):
                form_data['rate'] = rate_id
                formats.append(self._extract_stream_format(
                    self._download_json(
                        f'https://www.douyu.com/lapi/live/getH5Play/{room_id}',
                        video_id, note=f'Downloading livestream format {rate_id}',
                        data=urlencode_postdata(form_data))))

        return {
            'id': room_id,
            'formats': formats,
            'is_live': True,
            **traverse_obj(room, {
                'display_id': ('url', {str_or_none}, {lambda i: i[1:] if i else None}),
                'title': ('room_name', {str_or_none}, {unescapeHTML}),
                'description': ('show_details', {str_or_none}),
                'uploader': ('nickname', {str_or_none}),
                'thumbnail': ('room_src', {url_or_none}),
            })
        }


class DouyuShowIE(DouyuBaseIE):
    _VALID_URL = r'https?://v(?:mobile)?\.douyu\.com/show/(?P<id>[0-9a-zA-Z]+)'

    _TESTS = [{
        'url': 'https://v.douyu.com/show/mPyq7oVNe5Yv1gLY',
        'info_dict': {
            'id': 'mPyq7oVNe5Yv1gLY',
            'ext': 'ts',
            'title': '四川人小时候的味道“蒜苗回锅肉”，传统菜不能丢，要常做来吃',
            'duration': 633,
            'thumbnail': str,
            'uploader': '美食作家王刚V',
            'uploader_id': 'OVAO4NVx1m7Q',
            'timestamp': 1661850002,
            'upload_date': '20220830',
            'view_count': int,
            'tags': ['美食', '美食综合'],
        },
    }, {
        'url': 'https://vmobile.douyu.com/show/rjNBdvnVXNzvE2yw',
        'only_matching': True,
    }]

    _FORMATS = {
        'super': '原画',
        'high': '超清',
        'normal': '高清',
    }

    _QUALITIES = {
        'super': -1,
        'high': -2,
        'normal': -3,
    }

    _RESOLUTIONS = {
        'super': '1920x1080',
        'high': '1280x720',
        'normal': '852x480',
    }

    def _sign(self, sign_func, vid, video_id):
        return self._calc_sign(sign_func, vid, uuid.uuid4().hex, round(time.time()), video_id)

    def _real_extract(self, url):
        url = url.replace('vmobile.', 'v.')
        video_id = self._match_id(url)

        webpage = self._download_webpage(url, video_id)

        video_info_str = self._search_regex(
            r'<script>window\.\$DATA=({[^<]+});?</script>', webpage, 'video info')
        video_info = self._parse_json(
            re.sub(r'([{,])(\w+):', r'\1"\2":', video_info_str), video_id)

        js_sign_func = self._search_regex(r'<script>([^<]+ub98484234.*?)</script>', webpage, 'JS sign func')
        form_data = {
            'vid': video_id,
            **self._sign(js_sign_func, video_info['ROOM']['point_id'], video_id),
        }
        url_info = self._download_json(
            'https://v.douyu.com/api/stream/getStreamUrl', video_id,
            data=urlencode_postdata(form_data), note="Downloading video formats")

        formats = []
        for name, url in traverse_obj(url_info, ('data', 'thumb_video')).items():
            video_url = traverse_obj(url, ('url', {url_or_none}))
            if video_url:
                formats.append({
                    'format': self._FORMATS.get(name),
                    'format_id': name,
                    'url': video_url,
                    'quality': self._QUALITIES.get(name),
                    'ext': 'ts' if '.m3u8' in video_url else determine_ext(video_url),
                    **parse_resolution(self._RESOLUTIONS.get(name))
                })
            else:
                self.to_screen(
                    f'"{self._FORMATS.get(name, name)}" format may requires logging in. {self._login_hint()}')

        return {
            'id': video_id,
            'formats': formats,
            **traverse_obj(video_info, ('DATA', {
                'title': ('content', 'title', {str_or_none}),
                'uploader': ('content', 'author', {str_or_none}),
                'uploader_id': ('content', 'up_id', {str_or_none}),
                'duration': ('content', 'video_duration', {int_or_none}),
                'thumbnail': ('content', 'video_pic', {url_or_none}),
                'timestamp': ('content', 'create_time', {int_or_none}),
                'view_count': ('content', 'view_num', {int_or_none}),
                'tags': ('videoTag', ..., 'tagName', {str_or_none}),
            }))
        }
