# coding: utf-8
'''
Welcome to DeviceAtlas Cloud! All you need to get going is to set your
DeviceAtlas licence key below and import this module into your code.

DeviceAtlas Cloud API

Device data can then be retrieved as follows:

    Edit this file:
        Set your licence key to LICENCE_KEY =

    Import the API:
        import DeviceAtlasCloud.Client
    
    Create DA Cloud API object:
        da = DeviceAtlasCloud.Client.Client()

    Get device data:

        Generally:
            data = da.getDeviceData()

        In a django view you have to provide the headers dictoionary:
            data = da.getDeviceData(request.META)

        Or manually provide a dictionary of http headers:
            data = da.getDeviceData({HTTP-HEADERS})

If you are using linux un-comment lines 55 and 360 to use file lock on cache file

The returned data will be as:

    data['properties'] an dictionary of device properties
    data['_error']     will exist if any errors happened while fetching data
    data['_useragent'] the useragent that was used to query data
    data['_source']    shows where the data came from and is one of:
                            da.SOURCE_COOKIE
                            da.SOURCE_FILE_CACHE
                            da.SOURCE_CLOUD
                            da.SOURCE_NONE

© 2013 Afilias Technologies Ltd (dotMobi). All rights reserved

'''

import sys, os, json, tempfile, time, atexit
from hashlib import md5
from pprint import PrettyPrinter
from random import shuffle, randint
from google.appengine.api import memcache
#import fcntl
if sys.version_info[0] == 2:
    # python 2:
    from urllib2 import Request, quote, urlopen
else:
    # python 3:
    from urllib.request import Request, urlopen, quote


class Client:

    ############### BASIC SETUP ################################################

    LICENCE_KEY = 'paste-licence-key-here'

    # true:  server preference is decided by the API (faster server is preferred) 
    # false: server preference is SERVERS sort order (top server is preferred)
    AUTO_SERVER_RANKING = True

    # list of cloud service provider end points
    # server preference is decided from this list
    SERVERS = (
        {'host': 'region0.deviceatlascloud.com', 'port': 80},
        {'host': 'region1.deviceatlascloud.com', 'port': 80},
        {'host': 'region2.deviceatlascloud.com', 'port': 80},
        {'host': 'region3.deviceatlascloud.com', 'port': 80},
    )

    ############### ADVANCED SETUP #############################################
    # edit these if you want to tweak behaviour

    DEBUG = False
    # build in test user agent
    TEST_USERAGENT        = 'Mozilla/5.0 (Linux; U; Android 2.3.3; en-gb; GT-I9100 Build/GINGERBREAD) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1'
    # time (seconds) to wait for each cloud server to give service
    CLOUD_SERVICE_TIMEOUT = 2
    # use device data which is created by the DeviceAtlas Client Side Component if exists
    USE_CLIENT_COOKIE     = True
    # memcache cloud results in files (Must use on Google App Engine)
    USE_MEMCACHE         = True
    # cache cloud results in files
    USE_FILE_CACHE        = False
    # memcache expire (for both file and cookie) 2592000 = 30 days in seconds
    MEMCACHE_ITEM_EXPIRY_SEC = 2592000
    # cache expire (for both file and cookie) 2592000 = 30 days in seconds
    CACHE_ITEM_EXPIRY_SEC = 2592000
    # file cache > directory name
    CACHE_NAME            = 'deviceatlas_cache_py'
    # memcache > prefix name
    MEMCACHE_KEY_PREFIX   = 'deviceAtlas_'
    # memcache > key for server rankings
    MEMCACHE_KEY_SERVER_RANKS = 'deviceAtlas_serverRanks'
    # file cache > leave as true to put cache in systems default temp directory
    USE_SYSTEM_TEMP_DIR   = True
    # file cache > this is only used if USE_SYSTEM_TEMP_DIR is false
    CUSTOM_CACHE_DIR      = '/path/to/your/cache/'
    # true:  extra headers are sent with each request to the service
    # false: only select headers which are essential for detection are sent
    SEND_EXTRA_HEADERS    = False
    # name of the cookie created by "DeviceAtlas Client Side Component"
    CLIENT_COOKIE_NAME    = 'DAPROPS'
    # when ranking servers, if a server fails more than this number phase it out
    AUTO_SERVER_RANKING_MAX_FAILURE  = 1
    # number of requests to send when testing server latency
    AUTO_SERVER_RANKING_NUM_REQUESTS = 3
    # server preferred list will be updated when older than this amount of minutes
    AUTO_SERVER_RANKING_LIFETIME     = 1440
    # auto ranking = false > if top server fails it will be phased out for this amount of minutes
    SERVER_PHASEOUT_LIFETIME         = 1440
    # memcache expire (for server rank) 300 = 5 mins in seconds
    MEMCACHE_SERVER_RANKS_EXPIRY_SEC = 300

    ############### END OF SETUP, do not edit below this point! ################


    ############### CONSTANTS ##################################################
    API_VERSION           = 'python/1.3'
    # keys of dictionary returned by getDeviceData()
    USERAGENT             = '_useragent'
    SOURCE                = '_source'
    ERROR                 = '_error'
    PROPERTIES            = 'properties'
    # device data source
    SOURCE_COOKIE         = 'cookie'
    SOURCE_MEMCACHE     = 'memcache'
    SOURCE_FILE_CACHE     = 'cache'
    SOURCE_CLOUD          = 'cloud'
    SOURCE_NONE           = 'none'
    # headers
    DA_HEADER_PREFIX      = 'X-DA-'
    CLIENT_COOKIE_HEADER  = 'Client-Properties'
    # cloud service
    CLOUD_PATH            = '/v1/detect/properties?licencekey=%s&useragent=%s'

    # a list of headers from the end user to pass to DeviceAtlas Cloud. These
    # help with detection, especially if a third party browser or a proxy
    # changes the original user-agent.
    ESSENTIAL_HEADERS = (
        'HTTP_X_PROFILE',
        'HTTP_X_WAP_PROFILE',
        'HTTP_X_ATT_DEVICEID',
        'HTTP_ACCEPT',
        'HTTP_ACCEPT_LANGUAGE',
    )
    # a list of headers which may contain the original user agent.
    # this headers are sent to cloud server beside ESSENTIAL_HEADERS
    ESSENTIAL_USER_AGENT_HEADERS = (
        'HTTP_X_DEVICE_USER_AGENT',
        'HTTP_X_ORIGINAL_USER_AGENT',
        'HTTP_X_OPERAMINI_PHONE_UA',
        'HTTP_X_SKYFIRE_PHONE',
        'HTTP_X_BOLT_PHONE_UA',
        'HTTP_DEVICE_STOCK_UA',
        'HTTP_X_UCBROWSER_DEVICE_UA',
    )
    # a list of additional headers to send to DeviceAtlas. These are not sent
    # by default. These headers can be used for carrier detection and geoip.
    EXTRA_HEADERS = (
        'HTTP_CLIENT_IP',
        'HTTP_X_FORWARDED_FOR',
        'HTTP_X_FORWARDED',
        'HTTP_FORWARDED_FOR',
        'HTTP_FORWARDED',
        'HTTP_PROXY_CLIENT_IP',
        'HTTP_WL_PROXY_CLIENT_IP',
        'REMOTE_ADDR',
    )

    rankOnDestruct   = False
    calledServer = None

    pp = PrettyPrinter(indent=4)


    def __init__(self):
        # if headers are passed to getDeviceData then put them in this variable
        # None = when os.environ is used as headers container
        self.__headers = None


    def getDeviceData(self, headers={}, test_mode=False):
        '''
        Get device data from DeviceAtlas Cloud. Once data has been returned from
        DeviceAtlas Cloud it can be cached locally to speed up subsequent requests.
        If device data provided by "DeviceAtlas Client Side Component" exists in
        a cookie then cloud data will be merged with the cookie data.
        @param dict headers    a dictionary of HTTP headers set manually
        @param bool test_mode  true = use a fake useragent to test and get results
        @return     dictionary {properties: {name: value,}, _source: data-source,
                            _useragent: string, _error: if-any-happens}
        '''

        if self.DEBUG:
            print "getting Device Data"
        # unify headers to standard form - compatibility with legacy API
        if headers == {}:
            headers = os.environ
        else:
            if 'user_agent' in headers:
                legacy_headers = {
                    'user_agent': 'HTTP_USER_AGENT',
                    'cookie':     'HTTP_COOKIE',
                }
                for header in self.ESSENTIAL_HEADERS:
                    legacy_headers[header.lower().replace('http_', '')] = header
                for header in self.ESSENTIAL_USER_AGENT_HEADERS:
                    legacy_headers[header.lower().replace('http_', '')] = header
                for header in self.EXTRA_HEADERS:
                    legacy_headers[header.lower().replace('http_', '')] = header
                new_headers = {}
                for header in headers:
                    headerX = header.lower().replace('-', '_').replace('http_', '')
                    if headerX in legacy_headers:
                        a = legacy_headers[headerX]
                        b = headers[header]
                        new_headers[a] = b
                        #new_headers[legacy_headers[headerX]] = headers[header]
        headers = new_headers
        if self.DEBUG:
            self.pp.pprint(headers)
        # get user agent
        user_agent = ''
        if test_mode:
            user_agent = self.TEST_USERAGENT
        elif 'HTTP_USER_AGENT' in headers:
            user_agent = headers['HTTP_USER_AGENT']
            del headers['HTTP_USER_AGENT']

        self.__headers = headers

        # if "DeviceAtlas Client Side Component" cookie has been created use the data
        cookie  = ''
        cookies = {}
        if self.USE_CLIENT_COOKIE:
            if 'HTTP_COOKIE' in headers:
                for raw in headers['HTTP_COOKIE'].split(';'):
                   raw_list = raw.split('=')
                   cookies[raw_list[0].strip()] = raw_list[1].strip()
                if self.CLIENT_COOKIE_NAME in cookies:
                    cookie = cookies[self.CLIENT_COOKIE_NAME]

        # get device data from cache or cloud
        results = {}
        source  = self.SOURCE_NONE
        try:
            # check mem cache for cached data - cache is in JSON format
            if self.USE_MEMCACHE:
                source  = self.SOURCE_MEMCACHE
                results = self.getMemCache(user_agent, cookie)
            # check file cache for cached data - cache is in JSON format
            elif self.USE_FILE_CACHE:
                source  = self.SOURCE_FILE_CACHE
                results = self.getFileCache(user_agent, cookie)

            if results:
                #results = json.loads(results)
                #self.pp.pprint('WTF')
                #self.pp.pprint(results)
                if self.PROPERTIES not in results:
                    results = None

            # use cloud service to get data
            if not results:
                source  = self.SOURCE_CLOUD
                results = self.__callCloudService(user_agent, cookie)
                # set caches for future queries
                if self.USE_MEMCACHE:
                    self.setMemCache(user_agent, cookie, results)
                elif self.USE_FILE_CACHE:
                    self.setFileCache(user_agent, cookie, results)

            # decode json
            if results:
                if self.PROPERTIES not in results:
                    raise Exception(
                        'Can not get device properties from "%s"' % device_data
                    )
            else:
                results = {}
    
        except Exception as err:
            results = {self.ERROR: str(err)}

        results[self.SOURCE]    = source
        results[self.USERAGENT] = user_agent
        return results


    def __convertHeaders(self, header_keys):
        '''
        Converts HTTP header names from HTTP_HEADER_NAME to X-DA-header-name
        '''
        headers     = self.__headers
        new_headers = {}
        for header in header_keys:
            if header.startswith('HTTP_'):
                key = header[5:].lower().replace('_', '-')
            else:
                key = header.lower().replace('_', '-')
            if headers and header in headers:
                new_headers[self.DA_HEADER_PREFIX + key] = headers[header]

        return new_headers


    def __callCloudService(self, user_agent, cookie):
        '''
        Get data from the DeviceAtlas Cloud service
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''
        if self.DEBUG:
            print ("connecting to Device Atlas service ")
        errors  = []
        servers = self.getServers()
        i       = 0

        for server in servers:
            response = self.__connectCloud(server, user_agent, cookie, errors)
            self.calledServer = server
            if response != None:
                # i = index of healthy server, all servers with index less than
                # i have failed, move them to the end of the list:
                # save list to cache
                # if param servers is provided it means only cache servers
                # without ranking them.
                if i > 0:
                    self.rankServers(servers[i:]+servers[:i])

                return response
            i += 1

        raise Exception(('\n').join(errors))


    def __connectCloud(self, server, user_agent, cookie, errors, latency_checker=False):
        '''
        Connect to a cloud server and get device data, return data or null
        '''
        if self.DEBUG:
            print ("connecting to Device Atlas server " + server['host'])
        # add "essential" headers
        # add any Opera or any other special headers as these may contain
        # extra device information
        headers = self.__convertHeaders(
            self.ESSENTIAL_HEADERS +
            self.ESSENTIAL_USER_AGENT_HEADERS
        )
        # API info
        headers[self.DA_HEADER_PREFIX + 'Version'] = self.API_VERSION
        # add the "DeviceAtlas Client Side Component" cookie data
        if cookie:
            headers[self.DA_HEADER_PREFIX + self.CLIENT_COOKIE_HEADER] = cookie
        # latency checker
        if latency_checker:
            headers[self.DA_HEADER_PREFIX+'Latency-Checker'] = '1'
        # add extra "optional" headers
        if self.SEND_EXTRA_HEADERS:
            headers.update(self.convertHeader(self.EXTRA_HEADERS))
        # build request
        req = Request(
            'http://' + server['host'] + ':' + str(server['port']) +
            self.CLOUD_PATH % (self.LICENCE_KEY, quote(user_agent))
        )

        for header in headers:
            req.add_header(header, headers[header])
        try:
            res  = urlopen(req, None, self.CLOUD_SERVICE_TIMEOUT)
            data = res.read().decode('utf8').strip()
            if data:
                device_data = json.loads(data)
                if self.PROPERTIES in device_data:
                    return device_data

                errors.append('Server ('+server['host']+') returned invalid data')
            else:
                errors.append('Server ('+server['host']+') returned nothing')

        except Exception as err:
            errors.append(
                'Error fetching DeviceAtlas data from Cloud server "' + \
                server['host'] + '". ' + str(err)
            )

        return None


    def setFileCache(self, user_agent, cookie, device_data):
        '''
        FILE CACHE > Cache device data into a file
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''

        path     = self.getFileCacheDir(user_agent, cookie)
        dir_name = os.path.dirname(path)

        try:
            if not os.path.exists(dir_name):
                os.makedirs(dir_name, mode=0o755)
            fp = open(path, 'w')
            #fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fp.write(json.dumps(device_data))
            fp.close()

        except IOError as err:
            if err.errno not in (11, 13):
                raise Exception(
                    'Can not write cache file data at ' + path + ' Error: ' + str(err)
                )

        except Exception as err:
            raise Exception(
                'Can not write cache file data at ' + path + ' Error: ' + str(err)
            )

    def setMemCache(self, user_agent, cookie, device_data):
        '''
        MEM CACHE > Cache device data into memcache
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''

        if self.DEBUG:
            print "memcaching devicedata " + user_agent

        key = self.getMemCacheHashKey(user_agent, cookie)

        memcache.set(key = key, value = device_data, time = self.MEMCACHE_ITEM_EXPIRY_SEC)


    def getMemCache(self, user_agent, cookie):
        '''
        MEM CACHE > Creates a memcache key for this item by taking the md5 hash.
        Uses key to retrieve memcache value.
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''

        if self.DEBUG:
            print ("reading memcached devicedata for " + user_agent)
        key = self.getMemCacheHashKey(user_agent, cookie)
        return memcache.get(key = key)

    def getFileCache(self, user_agent, cookie):
        '''
        FILE CACHE > Creates a cache path for this item by taking the md5 hash
        and using the first 4 characters to create a directory structure.
        This is done to prevent too many files existing in any one directory
        as this can lead to slowdowns
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''
        path = self.getFileCacheDir(user_agent, cookie)
        if os.path.exists(path) and \
           os.path.getmtime(path) + self.CACHE_ITEM_EXPIRY_SEC > time.time():

            for i in (1, 2, 3, 4):
                try:
                    fp = open(path)
                    device_data = fp.read()
                    fp.close()
                    return device_data

                except Exception as err:
                    time.sleep(1)

        return ''


    def getCacheBasePath(self):
        '''
        FILE CACHE > Returns the path to save the file cache, it can be the
        default path or the assigned one through the CUSTOM_CACHE_DIR constant
        '''
        if self.USE_SYSTEM_TEMP_DIR:
            base_path = tempfile.gettempdir()
        else:
            base_path = self.CUSTOM_CACHE_DIR

        return base_path + os.sep + self.CACHE_NAME + os.sep

    def getFileCacheDir(self, user_agent, cookie):
        '''
        FILE CACHE > Creates a cache path for this item by taking the md5 hash
        and using the first 4 characters to create a directory structure.
        This is done to prevent too many files existing in any one directory
        as this can lead to slowdowns
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''
        headers = self.__headers
        # cache key - combination of user agent and cookie
        for header in self.ESSENTIAL_USER_AGENT_HEADERS:
            if header in headers:
                user_agent += headers[header]
                break

        key = md5(('py' + user_agent + cookie).encode('utf-8')).hexdigest()
        return \
            self.getCacheBasePath() +\
            key[0:2] +\
            os.sep +\
            key[2:4] +\
            os.sep +\
            key[4:len(key)]


    def getMemCacheHashKey(self, user_agent, cookie):
        '''
        MEM CACHE > Creates a cache key for this item by taking the md5 hash
        @param string cookie "DeviceAtlas Client Side Component" cookie data
        '''

        if self.DEBUG:
            print "getting memcache hash key for " + user_agent
        headers = self.__headers
        # cache key - combination of user agent and cookie
        for header in self.ESSENTIAL_USER_AGENT_HEADERS:
            if header in headers:
                user_agent += headers[header]
                break

        key = md5(('py' + user_agent + cookie).encode('utf-8')).hexdigest()
        if self.DEBUG:
            print(self.MEMCACHE_KEY_PREFIX + key)
        return self.MEMCACHE_KEY_PREFIX + key


    def getServersLatencies(self, numRequests=AUTO_SERVER_RANKING_NUM_REQUESTS):
        '''
        Get servers and the latencies to provide service.
        @param  number number of requests to do when testing an end pint
        @return dict {{avg:, latencies:, server:, port:},}
        '''

        if self.DEBUG:
            print "getting server latencies"
        # test servers in a randomly order
        servers = self.SERVERS
        seed    = list(range(len(servers)))
        shuffle(seed)

        for i in seed:
            latencies = self.getServerLatency(servers[i], numRequests)
            servers[i]['latencies'] = latencies
            if -1 in latencies:
                servers[i]['avg'] = -1
            else:
                servers[i]['avg'] = sum(servers[i]['latencies']) / numRequests
        
        return servers


    def getServerLatency(self, server, numRequests):
        '''
        Send request(s) to a server and return the latencies
        '''

        if self.DEBUG:
            print "getting server latency"
        failures  = 0
        latencies = []
        # ignore the first call because it can take an unreal long time
        for i in range(numRequests + 1):
            if failures < self.AUTO_SERVER_RANKING_MAX_FAILURE:
                errors = []
                start = time.time()

                response = self.__connectCloud(
                    server,
                    self.TEST_USERAGENT,
                    '',
                    errors
                )

                if errors == [] and response != None:
                    if i > 0:
                        latencies.append((time.time() - start) * 1000)
                    continue

                failures += 1
                latencies.append(-1)

        return latencies


    def getServers(self):
        '''
        Get server list sorted by preference.
        @return dictionary Nodes/Instances list
        '''


        if self.DEBUG:
            print "getting servers"

        if self.AUTO_SERVER_RANKING:
            # fetch server ranked list from cache if exists
            cache = memcache.get(key = self.MEMCACHE_KEY_SERVER_RANKS)
            if cache != None:
                return json.loads(cache)
            self.rankOnDestruct = True

        return self.SERVERS


    def rankServers(self, servers=[]):
        '''
         Rank DA cloud servers then put ranked server list in memcache.
         @param  servers array None: rank and memcache automatically
                               []: brutally memcache given server list without ranking
         @return bool state of success
        '''

        if self.DEBUG:
            print "ranking servers"
        # rank servers
        if servers == []:
            for server in self.getServersLatencies():
                if server['avg'] != -1:
                    servers.append(server)
            # no server detected
            if servers == []:
                return False
            # sort by latency ASC
            servers.sort(key=lambda x: x['avg'])
        # cache ranked servers
        ok       = True
        # try to put cache
        return memcache.set(key = self.MEMCACHE_KEY_SERVER_RANKS, value = json.dumps(servers), time = self.MEMCACHE_SERVER_RANKS_EXPIRY_SEC)


    def getCloudUrl(self):
        '''
        Get the last DA cloud service server used to get property
        (returns None if cache was used).
        @return None: properties came from cache/no property was fetched or
                {host: server-address, port: server-port}
        '''
        return self.calledServer


    def __del__(self):
        '''
        If server list needs to be resorted or build > when object is deleted
        '''
        if self.rankOnDestruct:
            self.rankServers()




def test():
    '''
    Basic tests of cloud lookup
    '''
    # create a da Client object
    da = Client()
    # create PrettyPrinter for displaying results
    pp = PrettyPrinter(indent=4)

    # larger set of headers
    headers = {
        'User-agent': 'Mozilla/5.0 (Linux; U; Android 2.2; zh-cn; HTC_Desire_A8181 Build/FRF91) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1',
        'Accept': 'application/xml,application/xhtml+xml,text/html;q=0.9,text/plain;q=0.8,image/png,*/*;q=0.5',
        'Accept-language': 'zh-CN, en-US',
        'x-wap-profile': 'http://www.htcmms.com.tw/Android/Common/Bravo/HTC_Desire_A8181.xml',
        'Cookie': 'DACACHEN=accessDom-js.supportBasicJavaScript-displayPpi-js.indexedDB-js.webSockets-js.querySelector-hscsd-js.geoLocation-flashCapable-js.json-isMediaPlayer-isTablet-osWindowsPhone-js.supportConsoleLog-isSetTopBox-memoryLimitDownload-js.deviceOrientation-mobileDevice-osAndroid-osBada-html.inlinesvg-displayHeight-jsr118-image.Png-isEReader-js.supportEvents-js.webGl-image.Gif89a-js.modifyCss-isMobilePhone-browserVersion-js.modifyDom-css.transitions-jsr37-drmOmaCombinedDelivery-uriSchemeTel-usableDisplayWidth-jsr30-https-image.Jpg-osVersion-edge-vendor-memoryLimitMarkup-jsr139-css.columns-markup.xhtmlMp12-markup.xhtmlMp11-displayColorDepth-deviceAspectRatio-js.sessionStorage-isGamesConsole-markup.xhtmlMp10-markup.xhtmlBasic10-browserName-html.audio-image.Gif87-osRim-devicePixelRatio-cookieSupport-markup.wml1-gprs-js.applicationCache-umts-js.webSqlDatabase-marketingName-hsdpa-js.webWorkers-vCardDownload-js.deviceMotion-touchScreen-osWebOs-isTV-osiOs-js.touchEvents-js.supportEventListener-model-html.svg-drmOmaForwardLock-js.xhr-html.canvas-displayWidth-id-usableDisplayHeight-osWindowsMobile-uriSchemeSmsTo-uriSchemeSms-drmOmaSeparateDelivery-osSymbian-yearReleased-css.transforms-js.localStorage-jqm-memoryLimitEmbeddedMedia-html.video-csd-css.animations-userMedia-client_props-generation; DACACHEV=%5Btrue%2Ctrue%2C203%2Ctrue%2Ctrue%2Ctrue%2Cfalse%2Ctrue%2Ctrue%2Ctrue%2Cfalse%2Cfalse%2Cfalse%2Ctrue%2Cfalse%2C0%2Ctrue%2Ctrue%2Ctrue%2Cfalse%2Ctrue%2C800%2Cfalse%2Ctrue%2Cfalse%2Ctrue%2Ctrue%2Ctrue%2Ctrue%2Ctrue%2C%224.0%22%2Ctrue%2Ctrue%2Cfalse%2Ctrue%2Ctrue%2C480%2Cfalse%2Ctrue%2Ctrue%2C%222.3.3%22%2Cfalse%2C%22Samsung%22%2C2000000%2Cfalse%2Ctrue%2Ctrue%2Ctrue%2C24%2C%2216%5C%2F9%22%2Ctrue%2Cfalse%2Ctrue%2Ctrue%2C%22Android+Browser%22%2Ctrue%2Ctrue%2Cfalse%2C1%2Ctrue%2Cfalse%2Ctrue%2Ctrue%2Cfalse%2Cfalse%2C%22Galaxy+S2%22%2Cfalse%2Ctrue%2Cfalse%2Ctrue%2Ctrue%2Cfalse%2Cfalse%2Cfalse%2Cfalse%2Ctrue%2C%22GT-I9100+Galaxy+S2%22%2Ctrue%2Ctrue%2Ctrue%2Ctrue%2C480%2C2410065%2C800%2Cfalse%2Ctrue%2Ctrue%2Ctrue%2Cfalse%2C2011%2Ctrue%2Ctrue%2Ctrue%2C0%2Ctrue%2Cfalse%2Ctrue%2Cfalse%2C%22eb17c1b1cc14f47342dfd6a0096490ee%22%2C2%5D; DAPROPS="bjs.webGl:1|bjs.geoLocation:1|bjs.webSqlDatabase:0|bjs.indexedDB:1|bjs.webSockets:1|bjs.localStorage:1|bjs.sessionStorage:1|bjs.webWorkers:1|bjs.applicationCache:1|bjs.supportBasicJavaScript:1|bjs.modifyDom:1|bjs.modifyCss:1|bjs.supportEvents:1|bjs.supportEventListener:1|bjs.xhr:1|bjs.supportConsoleLog:1|bjs.json:1|bjs.deviceOrientation:1|bjs.deviceMotion:1|bjs.touchEvents:0|bjs.querySelector:1|bhtml.canvas:1|bhtml.video:1|bhtml.audio:1|bhtml.svg:1|bhtml.inlinesvg:1|bcss.animations:1|bcss.columns:1|bcss.transforms:1|bcss.transitions:1|idisplayColorDepth:24|bcookieSupport:1|idevicePixelRatio:1|sdeviceAspectRatio:16/9|bflashCapable:1|baccessDom:1|buserMedia:0"',
    }

    # test mode, uses a default user agent to get data
    # if "DeviceAtlas Client Side Component" cookie exists it will be used
    data = da.getDeviceData(test_mode=True)

    # headers are set manually
    # if "DeviceAtlas Client Side Component" cookie exists it will be used
    data = da.getDeviceData(headers)
    
    # headers will be fetched from os.environ
    # if "DeviceAtlas Client Side Component" cookie exists it will be used
    #data = da.getDeviceData()

    # django - headers are set manually
    # if "DeviceAtlas Client Side Component" cookie exists it will be used
    #data = da.getDeviceData(request.META)

    # print results
    pp.pprint(data)




if __name__ == '__main__':
    test()
