import functools
import json
import time
from http.cookiejar import CookieJar
import urllib.parse
import urllib.request

from .gigya import GigyaBaseIE
from ..networking.exceptions import HTTPError
from ..utils import (
    ExtractorError,
    clean_html,
    extract_attributes,
    float_or_none,
    get_element_by_class,
    get_element_html_by_class,
    int_or_none,
    join_nonempty,
    jwt_encode_hs256,
    make_archive_id,
    parse_age_limit,
    parse_iso8601,
    str_or_none,
    strip_or_none,
    traverse_obj,
    url_or_none,
    urlencode_postdata,
)


class VRTBaseIE(GigyaBaseIE):
    _GEO_BYPASS = False

#     _PLAYER_INFO = {
#         'platform': 'desktop',
#         'app': {
#            'type': 'browser',
#            'name': 'Chrome'
#            },
#         'device': 'undefined (undefined)',
#         'os': {
#            'name': 'Windows',
#            'version': 'x86_64'
#            },
#         'player': {
#            'name': 'VRT web player',
#            'version': '3.2.6-prod-2023-09-11T12:37:41'
#            }
#         }

    _VIDEOPAGE_QUERY = "query VideoPage($pageId: ID!) {\n  page(id: $pageId) {\n    ... on EpisodePage {\n      id\n      title\n      permalink\n      seo {\n        ...seoFragment\n        __typename\n      }\n      socialSharing {\n        ...socialSharingFragment\n        __typename\n      }\n      trackingData {\n        data\n        perTrigger {\n          trigger\n          data\n          template {\n            id\n            __typename\n          }\n          __typename\n        }\n        __typename\n      }\n      ldjson\n      components {\n        __typename\n        ... on IComponent {\n          componentType\n          __typename\n        }\n      }\n      episode {\n        id\n        title\n        available\n        whatsonId\n        brand\n        brandLogos {\n          type\n          width\n          height\n          primary\n          mono\n          __typename\n        }\n        logo\n        primaryMeta {\n          ...metaFragment\n          __typename\n        }\n        secondaryMeta {\n          ...metaFragment\n          __typename\n        }\n        image {\n          ...imageFragment\n          __typename\n        }\n        durationRaw\n        durationValue\n        durationSeconds\n        onTimeRaw\n        offTimeRaw\n        ageRaw\n        regionRaw\n        announcementValue\n        name\n        episodeNumberRaw\n        episodeNumberValue\n        subtitle\n        richDescription {\n          __typename\n          html\n        }\n        program {\n          id\n          link\n          title\n          __typename\n        }\n        watchAction {\n          streamId\n          videoId\n          episodeId\n          avodUrl\n          resumePoint\n          __typename\n        }\n        shareAction {\n          title\n          description\n          image {\n            templateUrl\n            __typename\n          }\n          url\n          __typename\n        }\n        favoriteAction {\n          id\n          title\n          favorite\n          programWhatsonId\n          programUrl\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\nfragment metaFragment on MetaDataItem {\n  __typename\n  type\n  value\n  shortValue\n  longValue\n}\nfragment imageFragment on Image {\n  objectId\n  id: objectId\n  alt\n  title\n  focalPoint\n  templateUrl\n}\nfragment seoFragment on SeoProperties {\n  __typename\n  title\n  description\n}\nfragment socialSharingFragment on SocialSharingProperties {\n  __typename\n  title\n  description\n  image {\n    __typename\n    id: objectId\n    templateUrl\n  }\n}"

    # From https://player.vrt.be/vrtnws/js/main.js & https://player.vrt.be/ketnet/js/main.8cdb11341bcb79e4cd44.js
    _JWT_KEY_ID = '0-0Fp51UZykfaiCJrfTE3+oMI8zvDteYfPtR+2n1R+z8w='
    _JWT_SIGNING_KEY = '2a9251d782700769fb856da5725daf38661874ca6f80ae7dc2b05ec1a81a24ae'
#     _JWT_SIGNING_KEY = 'b5f500d55cb44715107249ccd8a5c0136cfb2788dbb71b90a4f142423bacaf38'  # -dev
    # player-stag.vrt.be key:    d23987504521ae6fbf2716caca6700a24bb1579477b43c84e146b279de5ca595
    # player.vrt.be key:         2a9251d782700769fb856da5725daf38661874ca6f80ae7dc2b05ec1a81a24ae

    def _extract_formats_and_subtitles(self, data, video_id):
        if traverse_obj(data, 'drm'):
            self.report_drm(video_id)

        formats, subtitles = [], {}
        for target in traverse_obj(data, ('targetUrls', lambda _, v: url_or_none(v['url']) and v['type'])):
            format_type = target['type'].upper()
            format_url = target['url']
            if format_type in ('HLS', 'HLS_AES'):
                fmts, subs = self._extract_m3u8_formats_and_subtitles(
                    format_url, video_id, 'mp4', m3u8_id=format_type, fatal=False)
                formats.extend(fmts)
                self._merge_subtitles(subs, target=subtitles)
            elif format_type == 'HDS':
                formats.extend(self._extract_f4m_formats(
                    format_url, video_id, f4m_id=format_type, fatal=False))
            elif format_type == 'MPEG_DASH':
                fmts, subs = self._extract_mpd_formats_and_subtitles(
                    format_url, video_id, mpd_id=format_type, fatal=False)
                formats.extend(fmts)
                self._merge_subtitles(subs, target=subtitles)
            elif format_type == 'HSS':
                fmts, subs = self._extract_ism_formats_and_subtitles(
                    format_url, video_id, ism_id='mss', fatal=False)
                formats.extend(fmts)
                self._merge_subtitles(subs, target=subtitles)
            else:
                formats.append({
                    'format_id': format_type,
                    'url': format_url,
                })

        for sub in traverse_obj(data, ('subtitleUrls', lambda _, v: v['url'] and v['type'] == 'CLOSED')):
            subtitles.setdefault('nl', []).append({'url': sub['url']})

        return formats, subtitles

    def _call_api(self, video_id, client='null', id_token=None, version='v2'):
#         player_info = {'exp': (round(time.time(), 3) + 900), **self._PLAYER_INFO}
#         player_info_jwt = jwt_encode_hs256(player_info, self._JWT_SIGNING_KEY, headers={
#                     'kid': self._JWT_KEY_ID
#                 }).decode()

        headers = {
                    'Content-Type': 'application/json'
                    }

        data = {
                'identityToken': id_token or self._cookies['vrtnu-site_profile_vt'],
#                 'playerInfo': player_info_jwt
                }

        json_response = self._download_json(
            f'https://media-services-public.vrt.be/vualto-video-aggregator-web/rest/external/{version}/tokens',
           None, 'Downloading player token', headers=headers, data=json.dumps(data).encode())
        player_token = json_response['vrtPlayerToken']

        return self._download_json(
            f'https://media-services-public.vrt.be/vualto-video-aggregator-web/rest/external/{version}/videos/{video_id}',
            video_id, 'Downloading API JSON', query={
                'vrtPlayerToken': player_token,
                'client': client,
            })


class VRTIE(VRTBaseIE):
    IE_DESC = 'VRT NWS, Flanders News, Flandern Info and Sporza'
    _VALID_URL = r'https?://(?:www\.)?(?P<site>vrt\.be/vrtnws|sporza\.be)/[a-z]{2}/\d{4}/\d{2}/\d{2}/(?P<id>[^/?&#]+)'
    _TESTS = [{
        'url': 'https://www.vrt.be/vrtnws/nl/2019/05/15/beelden-van-binnenkant-notre-dame-een-maand-na-de-brand/',
        'info_dict': {
            'id': 'pbs-pub-7855fc7b-1448-49bc-b073-316cb60caa71$vid-2ca50305-c38a-4762-9890-65cbd098b7bd',
            'ext': 'mp4',
            'title': 'Beelden van binnenkant Notre-Dame, één maand na de brand',
            'description': 'md5:6fd85f999b2d1841aa5568f4bf02c3ff',
            'duration': 31.2,
            'thumbnail': 'https://images.vrt.be/orig/2019/05/15/2d914d61-7710-11e9-abcc-02b7b76bf47f.jpg',
        },
        'params': {'skip_download': 'm3u8'},
    }, {
        'url': 'https://sporza.be/nl/2019/05/15/de-belgian-cats-zijn-klaar-voor-het-ek/',
        'info_dict': {
            'id': 'pbs-pub-e1d6e4ec-cbf4-451e-9e87-d835bb65cd28$vid-2ad45eb6-9bc8-40d4-ad72-5f25c0f59d75',
            'title': 'Trailer \'Heizel 1985\'',
            'thumbnail': 'https://images.vrt.be/orig/2022/09/07/6e44ce6f-2eb3-11ed-b07d-02b7b76bf47f.jpg',
            'ext': 'mp4',
            'title': 'De Belgian Cats zijn klaar voor het EK',
            'description': 'Video: De Belgian Cats zijn klaar voor het EK mét Ann Wauters | basketbal, sport in het journaal',
            'duration': 115.17,
            'thumbnail': 'https://images.vrt.be/orig/2019/05/15/11c0dba3-770e-11e9-abcc-02b7b76bf47f.jpg',
        },
        'params': {'skip_download': 'm3u8'},
    }]
    _NETRC_MACHINE = 'vrtnu'
    _APIKEY = '3_0Z2HujMtiWq_pkAjgnS2Md2E11a1AwZjYiBETtwNE-EoEHDINgtnvcAOpNgmrVGy'
    _CONTEXT_ID = 'R3595707040'
    _REST_API_BASE_TOKEN = 'https://media-services-public.vrt.be/vualto-video-aggregator-web/rest/external/v2'
    _REST_API_BASE_VIDEO = 'https://media-services-public.vrt.be/media-aggregator/v2'
    _HLS_ENTRY_PROTOCOLS_MAP = {
        'HLS': 'm3u8_native',
        'HLS_AES': 'm3u8_native',
    }

    _authenticated = False

    def _perform_login(self, username, password):
        auth_info = self._gigya_login({
            'APIKey': self._APIKEY,
            'targetEnv': 'jssdk',
            'loginID': username,
            'password': password,
            'authMode': 'cookie',
        })

        if auth_info.get('errorDetails'):
            raise ExtractorError('Unable to login: VrtNU said: ' + auth_info.get('errorDetails'), expected=True)

        # Sometimes authentication fails for no good reason, retry
        login_attempt = 1
        while login_attempt <= 3:
            try:
                self._request_webpage('https://token.vrt.be/vrtnuinitlogin',
                                      None, note='Requesting XSRF Token', errnote='Could not get XSRF Token',
                                      query={'provider': 'site', 'destination': 'https://www.vrt.be/vrtnu/'})

                post_data = {
                    'UID': auth_info['UID'],
                    'UIDSignature': auth_info['UIDSignature'],
                    'signatureTimestamp': auth_info['signatureTimestamp'],
                    '_csrf': self._get_cookies('https://login.vrt.be').get('OIDCXSRF').value,
                }

                self._request_webpage(
                    'https://login.vrt.be/perform_login',
                    None, note='Performing login', errnote='perform login failed',
                    headers={}, query={
                        'client_id': 'vrtnu-site'
                    }, data=urlencode_postdata(post_data))

            except ExtractorError as e:
                if isinstance(e.cause, compat_HTTPError) and e.cause.code == 401:
                    login_attempt += 1
                    self.report_warning('Authentication failed')
                    self._sleep(1, None, msg_template='Waiting for %(timeout)s seconds before trying again')
                else:
                    raise e
            else:
                break

        self._authenticated = True

    def _real_extract(self, url):
        site, display_id = self._match_valid_url(url).groups()
        webpage = self._download_webpage(url, display_id)
        attrs = extract_attributes(get_element_html_by_class('vrtvideo', webpage) or '')

        asset_id = attrs.get('data-video-id') or attrs['data-videoid']
        publication_id = traverse_obj(attrs, 'data-publication-id', 'data-publicationid')
        if publication_id:
            asset_id = f'{publication_id}${asset_id}'
        client = traverse_obj(attrs, 'data-client-code', 'data-client') or self._CLIENT_MAP[site]

        data = self._call_api(asset_id, client)
        formats, subtitles = self._extract_formats_and_subtitles(data, asset_id)

        description = self._html_search_meta(
            ['og:description', 'twitter:description', 'description'], webpage)
        if description == '…':
            description = None

        return {
            'id': asset_id,
            'formats': formats,
            'subtitles': subtitles,
            'description': description,
            'thumbnail': url_or_none(attrs.get('data-posterimage')),
            'duration': float_or_none(attrs.get('data-duration'), 1000),
            '_old_archive_ids': [make_archive_id('Canvas', asset_id)],
            **traverse_obj(data, {
                'title': ('title', {str}),
                'description': ('shortDescription', {str}),
                'duration': ('duration', {functools.partial(float_or_none, scale=1000)}),
                'thumbnail': ('posterImageUrl', {url_or_none}),
            }),
        }


class NoRedirect(urllib.request.HTTPRedirectHandler):

    def http_error_302(self, req, fp, code, msg, headers):
        result = urllib.error.HTTPError(req.get_full_url(), code, msg, headers, fp)
        return result

    http_error_301 = http_error_303 = http_error_307 = http_error_302


class CookiePot(CookieJar):

    def __getitem__(self, name):
        for cookie in self:
            if cookie.name == name:
                return cookie.value
        return None

    def __str__(self):
        return '\n'.join(f'{cookie.name}={cookie.value}' for cookie in self)


class VrtNUIE(VRTBaseIE):
    IE_DESC = 'VRT MAX'
    _VALID_URL = r'https?://(?:www\.)?vrt\.be/(vrtmax|vrtnu)/a-z/(?:[^/]+/){2}(?P<id>[^/?#&]+)'
    _TESTS = [{
        # CONTENT_IS_AGE_RESTRICTED
        'url': 'https://www.vrt.be/vrtnu/a-z/de-ideale-wereld/2023-vj/de-ideale-wereld-d20230116/',
        'info_dict': {
            'id': 'pbs-pub-855b00a8-6ce2-4032-ac4f-1fcf3ae78524$vid-d2243aa1-ec46-4e34-a55b-92568459906f',
            'ext': 'mp4',
            'title': 'Tom Waes',
            'description': 'Satirisch actualiteitenmagazine met Ella Leyers. Tom Waes is te gast.',
            'timestamp': 1673905125,
            'release_timestamp': 1673905125,
            'series': 'De ideale wereld',
            'season_id': '1672830988794',
            'episode': 'Aflevering 1',
            'episode_number': 1,
            'episode_id': '1672830988861',
            'display_id': 'de-ideale-wereld-d20230116',
            'channel': 'VRT',
            'duration': 1939.0,
            'thumbnail': 'https://images.vrt.be/orig/2023/01/10/1bb39cb3-9115-11ed-b07d-02b7b76bf47f.jpg',
            'release_date': '20230116',
            'upload_date': '20230116',
            'age_limit': 12,
        },
    }, {
        'url': 'https://www.vrt.be/vrtnu/a-z/buurman--wat-doet-u-nu-/6/buurman--wat-doet-u-nu--s6-trailer/',
        'info_dict': {
            'id': 'pbs-pub-ad4050eb-d9e5-48c2-9ec8-b6c355032361$vid-0465537a-34a8-4617-8352-4d8d983b4eee',
            'ext': 'mp4',
            'title': 'Trailer seizoen 6 \'Buurman, wat doet u nu?\'',
            'description': 'md5:197424726c61384b4e5c519f16c0cf02',
            'timestamp': 1652940000,
            'release_timestamp': 1652940000,
            'series': 'Buurman, wat doet u nu?',
            'season': 'Seizoen 6',
            'season_number': 6,
            'season_id': '1652344200907',
            'episode': 'Aflevering 0',
            'episode_number': 0,
            'episode_id': '1652951873524',
            'display_id': 'buurman--wat-doet-u-nu--s6-trailer',
            'channel': 'VRT',
            'duration': 33.13,
            'thumbnail': 'https://images.vrt.be/orig/2022/05/23/3c234d21-da83-11ec-b07d-02b7b76bf47f.jpg',
            'release_date': '20220519',
            'upload_date': '20220519',
        },
        'params': {'skip_download': 'm3u8'},
    }]
    _NETRC_MACHINE = 'vrtnu'
    _authenticated = False
    _cookies = CookiePot()

    def _perform_login(self, username, password):

        # Disable automatic redirection to be able to
        # grab necessary info in intermediate step
        opener = urllib.request.build_opener(NoRedirect,urllib.request.HTTPCookieProcessor(self._cookies))

        # 1.a Visit 'login' URL. Get 'authorize' location and 'oidcstate' cookie
        res = opener.open('https://www.vrt.be/vrtnu/sso/login', None)
        auth_url = res.headers.get_all('Location')[0]

        # 1.b Follow redirection: visit 'authorize' URL. Get OIDCXSRF & SESSION cookies
        res = opener.open(auth_url, None)
        cookies_header = f'OIDCXSRF={self._cookies["OIDCXSRF"]}; SESSION={self._cookies["SESSION"]}'

        # 2. Perform login
        headers = {
                'Content-Type': 'application/json',
                'Oidcxsrf': self._cookies["OIDCXSRF"],
                'Cookie': cookies_header
                }
        post_data = { "loginID": f"{username}", "password": f"{password}", "clientId": "vrtnu-site" }
        res = self._request_webpage('https://login.vrt.be/perform_login', None, note='Performing login', errnote='Login failed', fatal=True, data=json.dumps(post_data).encode(), headers=headers)

        # TODO:
        #   . should this step be the new "refreshtoken" in _real_extract?

        # 3.a Visit 'authorize' again
        headers = {
                'Cookie': cookies_header
                }
        request = urllib.request.Request(auth_url, headers=headers)
        res = opener.open(request, None)
        callback_url = res.headers.get_all('Location')[0]

        # 3.b Visit 'callback'
        headers = {
                'Cookie': f'oidcstate={self._cookies["oidcstate"]}'
                }
        request = urllib.request.Request(callback_url, headers=headers)
        res = opener.open(request, None)

        self._authenticated = True


    def _real_extract(self, url):
        display_id = self._match_id(url)
        parsed_url = urllib.parse.urlparse(url)

        headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self._cookies["vrtnu-site_profile_at"]}'
                }

        data = {
                'operationName': 'VideoPage',
                'query': self._VIDEOPAGE_QUERY ,
                'variables': {
                    'pageId': f'{parsed_url.path.rstrip("/")}.model.json'
                    }
                }

        model_json = self._download_json(
            'https://www.vrt.be/vrtnu-api/graphql/v1',
            display_id, 'Downloading asset JSON', 'Unable to download asset JSON', headers=headers, data=json.dumps(data).encode())['data']['page']

        video_id = model_json['episode']['watchAction']['streamId']
        title =  model_json['seo']['title']
        season_number = int(model_json['episode']['onTimeRaw'][:4])
        ld_json = json.loads(model_json['ldjson'][1])

        streaming_json = self._call_api(video_id, client='vrtnu-web@PROD')
        formats, subtitles = self._extract_formats_and_subtitles(streaming_json, video_id)

        return {
            **traverse_obj(model_json, {
                'description': ('seo', 'description', {clean_html}),
                'timestamp': ( 'episode', 'onTimeRaw', {parse_iso8601}),
                'release_timestamp': ( 'episode', 'onTimeRaw', {parse_iso8601}),
                'series': ('episode', 'program', 'title'),
                'episode': ('episode', 'episodeNumberRaw', {str_or_none}),
                'episode_number': ('episode', 'episodeNumberRaw', {int_or_none}),
                'age_limit': ('episode', 'ageRaw', {parse_age_limit}),
                'display_id': ('episode', 'name', {parse_age_limit}),
            }),
            **traverse_obj(ld_json, {
                'season': ('partOfSeason', 'name'),
                'season_id': ('partOfSeason', '@id'),
                'episode_id': ('@id', {str_or_none}),
            }),
            'title': title,
            'season_number': season_number,
            'id': video_id,
            'channel': 'VRT',
            'formats': formats,
            'duration': float_or_none(streaming_json.get('duration'), 1000),
            'thumbnail': url_or_none(streaming_json.get('posterImageUrl')),
            'subtitles': subtitles,
            '_old_archive_ids': [make_archive_id('Canvas', video_id)],
        }


class KetnetIE(VRTBaseIE):
    _VALID_URL = r'https?://(?:www\.)?ketnet\.be/(?P<id>(?:[^/]+/)*[^/?#&]+)'
    _TESTS = [{
        'url': 'https://www.ketnet.be/kijken/m/meisjes/6/meisjes-s6a5',
        'info_dict': {
            'id': 'pbs-pub-39f8351c-a0a0-43e6-8394-205d597d6162$vid-5e306921-a9aa-4fa9-9f39-5b82c8f1028e',
            'ext': 'mp4',
            'title': 'Meisjes',
            'episode': 'Reeks 6: Week 5',
            'season': 'Reeks 6',
            'series': 'Meisjes',
            'timestamp': 1685251800,
            'upload_date': '20230528',
        },
        'params': {'skip_download': 'm3u8'},
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)

        video = self._download_json(
            'https://senior-bff.ketnet.be/graphql', display_id, query={
                'query': '''{
  video(id: "content/ketnet/nl/%s.model.json") {
    description
    episodeNr
    imageUrl
    mediaReference
    programTitle
    publicationDate
    seasonTitle
    subtitleVideodetail
    titleVideodetail
  }
}''' % display_id,
            })['data']['video']

        video_id = urllib.parse.unquote(video['mediaReference'])
        data = self._call_api(video_id, 'ketnet@PROD', version='v1')
        formats, subtitles = self._extract_formats_and_subtitles(data, video_id)

        return {
            'id': video_id,
            'formats': formats,
            'subtitles': subtitles,
            '_old_archive_ids': [make_archive_id('Canvas', video_id)],
            **traverse_obj(video, {
                'title': ('titleVideodetail', {str}),
                'description': ('description', {str}),
                'thumbnail': ('thumbnail', {url_or_none}),
                'timestamp': ('publicationDate', {parse_iso8601}),
                'series': ('programTitle', {str}),
                'season': ('seasonTitle', {str}),
                'episode': ('subtitleVideodetail', {str}),
                'episode_number': ('episodeNr', {int_or_none}),
            }),
        }


class DagelijkseKostIE(VRTBaseIE):
    IE_DESC = 'dagelijksekost.een.be'
    _VALID_URL = r'https?://dagelijksekost\.een\.be/gerechten/(?P<id>[^/?#&]+)'
    _TESTS = [{
        'url': 'https://dagelijksekost.een.be/gerechten/hachis-parmentier-met-witloof',
        'info_dict': {
            'id': 'md-ast-27a4d1ff-7d7b-425e-b84f-a4d227f592fa',
            'ext': 'mp4',
            'title': 'Hachis parmentier met witloof',
            'description': 'md5:9960478392d87f63567b5b117688cdc5',
            'display_id': 'hachis-parmentier-met-witloof',
        },
        'params': {'skip_download': 'm3u8'},
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)
        webpage = self._download_webpage(url, display_id)
        video_id = self._html_search_regex(
            r'data-url=(["\'])(?P<id>(?:(?!\1).)+)\1', webpage, 'video id', group='id')

        data = self._call_api(video_id, 'dako@prod', version='v1')
        formats, subtitles = self._extract_formats_and_subtitles(data, video_id)

        return {
            'id': video_id,
            'formats': formats,
            'subtitles': subtitles,
            'display_id': display_id,
            'title': strip_or_none(get_element_by_class(
                'dish-metadata__title', webpage) or self._html_search_meta('twitter:title', webpage)),
            'description': clean_html(get_element_by_class(
                'dish-description', webpage)) or self._html_search_meta(
                ['description', 'twitter:description', 'og:description'], webpage),
            '_old_archive_ids': [make_archive_id('Canvas', video_id)],
        }
