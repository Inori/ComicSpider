#-*-coding:utf-8-*-


import threading
import urllib.request
import urllib.parse
import urllib.error
import re
import os
import queue
from bs4 import BeautifulSoup
from selenium import webdriver


N_PRODUCER = 5
N_CUSTOMER = 15
N_JOB_QUEUE_SIZE = 200


def DebugPrint(log):
    print(log)


class StopToken(object):
    pass


class UrlDownloader(object):

    def __init__(self, url):
        self._url = url

    def GetRawData(self):
        header = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36'
        }

        request = urllib.request.Request(url = self._url, headers = header, method='GET')
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as http_error:
            DebugPrint(http_error)
            DebugPrint('Error URL: {}'.format(self._url))
            return None
        except UnicodeEncodeError as code_error:
            DebugPrint(code_error)
            DebugPrint('Error URL: {}'.format(self._url))
            DebugPrint('Try to standardize url.')

            new_url = self._StandardizeUrl(self._url)
            request = urllib.request.Request(url=new_url, headers=header, method='GET')
            try:
                response = urllib.request.urlopen(request)
            except Exception as e:
                DebugPrint(e)
                DebugPrint('Error URL after standardize:{}'.format(new_url))
                return None
        return response.read()


    def GetHtml(self):
        raw = self.GetRawData()
        if not raw:
            DebugPrint("Can't get raw content.")
            return ''

        charset = self._GetCharset(raw)
        return raw.decode(charset, errors='ignore')


    def GetHtmlByChrome(self):
        options = webdriver.ChromeOptions()
        options.headless = True
        browser = webdriver.Chrome('./chromedriver', options = options)
        html = ''
        try:
            browser.get(self._url)
            html = browser.page_source
        except Exception as e:
            DebugPrint(e)
        return html


    def _GetCharset(self, raw):
        pattern = re.compile('<( |\t)*meta.*charset=.*?>')
        s = pattern.search(raw.decode('ascii', errors='ignore'))

        if not s:
            return 'utf-8'

        line = s.group(0)
        if 'gbk' in line:
            return 'gbk'

        return 'utf-8'


    def _StandardizeUrl(self, old_url):
        result = urllib.parse.urlparse(old_url)
        parts = result.path.split('/')


        def is_ascii(string):
            for c in string:
                if ord(c) >= 0x00 and ord(c) <= 0xFF:
                    continue
                else:
                    return False
            return True

        for idx, part in enumerate(parts):
            if not part:
                continue

            if is_ascii(part):
                continue
            parts[idx] = urllib.parse.quote(part)

        path = '/'.join(parts)

        new_parts = (result.scheme, result.netloc, path, result.params, result.query, result.fragment)
        new_url = urllib.parse.urlunparse(new_parts)
        return new_url




class DownloadJob(object):

    def __init__(self, url, filename):
        self._url = url
        self._filename = filename

    def Download(self):
        if not self._url:
            DebugPrint('Got null url')
            return

        downloader = UrlDownloader(self._url)
        raw = downloader.GetRawData()
        if not raw:
            DebugPrint('Download failed: {}'.format(self._filename))
            return

        with open(self._filename, 'wb') as dst:
            dst.write(raw)

        title = os.path.basename(os.path.dirname(self._filename))
        name = os.path.basename(self._filename)
        DebugPrint('Downloading: {} -> {}'.format(title, name))




#producer
class BaseSpider(threading.Thread):

    def __init__(self, entries_queue, job_queue, root_dir):
        super().__init__()
        self._entries_queue = entries_queue
        self._job_queue = job_queue
        self._root_dir = root_dir


    def run(self):
        while True:
            entry_url = self._entries_queue.get()

            if entry_url == StopToken:
                break

            entry_name, page_count = self._GetEntryNameAndPageCount(entry_url)
            page_url_list = self._GetPageUrlList(entry_url, page_count)

            DebugPrint('Begin download: {}'.format(entry_name))

            dir_name = os.path.join(os.path.abspath(self._root_dir) , entry_name)
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)

            for idx, page_url in enumerate(page_url_list):
                img_url = self._GetImageUrl(page_url)

                DebugPrint('Add url to queue: {}'.format(img_url))

                _, ext_name = os.path.splitext(img_url)
                idx_str = '{:04d}'.format(idx) + ext_name
                filename = os.path.join(dir_name, idx_str)
                job = DownloadJob(img_url, filename)
                self._job_queue.put(job)

            self._entries_queue.task_done()


    @staticmethod
    def GetEntryList(url):
        raise Exception('pure virtual method')

    def _GetEntryNameAndPageCount(self, first_url):
        raise Exception('pure virtual method')

    def _GetPageUrlList(self, first_url, page_count):
        raise Exception('pure virtual method')

    def _GetImageUrl(self, page_url):
        raise Exception('pure virtual method')




class KukuSpider(BaseSpider):

    def __init__(self, entries_queue, job_queue, root_dir):
        super().__init__(entries_queue, job_queue, root_dir)


    @staticmethod
    def GetEntryList(url):
        html = UrlDownloader(url).GetHtml()
        if not html:
            DebugPrint('GetEntryList failed.')
            return []

        soup = BeautifulSoup(html, 'html.parser')
        # dl = soup.find('dl', id="comiclistn")
        dl = soup.select('#comiclistn')[0]
        dd_list = dl.find_all('dd')

        url_list = []
        for dd in dd_list:
            a = dd.find('a', string='①')
            url = a.get('href')
            url_list.append(url)

        return url_list


    #破刃之剑_Vol_1 | 共82页 | 当前第1页 | 跳转至第
    def _GetEntryNameAndPageCount(self, first_url):
        html = UrlDownloader(first_url).GetHtml()
        if not html:
            DebugPrint('_GetEntryNameAndPageCount failed.')
            return '', ''

        soup = BeautifulSoup(html, 'html.parser')

        entry_name = soup.title.string

        td = soup.select('body > table:nth-of-type(2) > tr > td')[0]
        title_string = td.next.string
        parts = title_string.split('|')
        count_string = parts[1].replace(' ', '')
        count_string = count_string[1:-1]
        page_count = int(count_string)

        return entry_name, page_count


    def _GetPageUrlList(self, first_url, page_count):

        url_list = []
        for i in range(1, page_count + 1):
            end_pos = first_url.rfind('/')
            url = first_url[:end_pos + 1] + str(i) + '.htm'
            url_list.append(url)

        return url_list

    # def _GetImageUrl(self, page_url):
    #     # html = UrlDownloader(page_url).GetHtml()
    #     html = UrlDownloader(page_url).GetHtmlByChrome()
    #     soup = BeautifulSoup(html, 'html.parser')
    #     td = soup.select('body > table:nth-of-type(2) > tbody > tr > td')[0]
    #     imgs = td.find_all('img')
    #     for img in imgs:
    #         src = img.get('src')
    #         if 'kuku' in src and '.jpg' in src:
    #             return src
    #
    #     DebugPrint('Can not found proper img, page url: {}'.format(page_url))
    #     return ''

    def _GetImageUrl(self, page_url):
        html = UrlDownloader(page_url).GetHtml()
        # html = UrlDownloader(page_url).GetHtmlByChrome()
        if not html:
            DebugPrint('_GetImageUrl failed.')
            return ''

        js_pat = re.compile('document.write\(.*?\)')
        s = js_pat.search(html)
        if not s:
            return ''

        js_line = s.group(0)
        url_pat = re.compile('\+"(.*?\.jpg)')
        s = url_pat.search(js_line)
        if not s:
            return ''

        url_part = s.group(1)
        url_prefix = 'http://n5.1whour.com/'
        url = url_prefix + url_part
        return url


class HanhanSpider(BaseSpider):

    @staticmethod
    def GetEntryList(url):
        raise Exception('pure virtual method')

    def _GetEntryNameAndPageCount(self, first_url):
        raise Exception('pure virtual method')

    def _GetPageUrlList(self, first_url, page_count):
        raise Exception('pure virtual method')

    def _GetImageUrl(self, page_url):
        raise Exception('pure virtual method')



#customer
class ComicDownloader(threading.Thread):

    def __init__(self, job_queue):
        super().__init__()
        self._job_queue = job_queue

    def run(self):
        while True:
            job = self._job_queue.get()

            if job == StopToken:
                break

            job.Download()

            self._job_queue.task_done()




class SpiderManager(object):

    def __init__(self, spider, url, root_dir):
        self._spider = spider
        self._url = url
        self._root_dir = root_dir


    def Process(self):

        entry_list = self._spider.GetEntryList(self._url)

        job_queue = queue.Queue(N_JOB_QUEUE_SIZE)
        entries_queue = queue.Queue(len(entry_list))


        for entry in entry_list:
            entries_queue.put(entry)


        producer_list = []
        for i in range(0, N_PRODUCER):
            t = self._spider(entries_queue, job_queue, self._root_dir)
            t.start()
            producer_list.append(t)


        customer_list = []
        for i in range(0, N_CUSTOMER):
            t = ComicDownloader(job_queue)
            t.start()
            customer_list.append(t)

        entries_queue.join()
        for i in range(0, N_PRODUCER):
            entries_queue.put(StopToken)

        for t in producer_list:
            t.join()

        job_queue.join()
        for i in range(0, N_CUSTOMER):
            job_queue.put(StopToken)

        for t in customer_list:
            t.join()

        DebugPrint('All jobs done.')





def main():

    d = UrlDownloader('')
    d._StandardizeUrl('http://n5.1whour.com/kuku8comic8/201105/20110531/话话话话/Comic.kukudm.com_1603G.jpg')

    url = 'http://comic.kukudm.com/comiclist/711/index.htm'
    manager = SpiderManager(KukuSpider, url, '/home/asuka/local/comic')
    manager.Process()



if __name__ == '__main__':
    main()