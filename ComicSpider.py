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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import selenium.common.exceptions as selenium_exception
from PIL import Image
from io import BytesIO

N_PRODUCER = 2
N_CUSTOMER = 3
N_JOB_QUEUE_SIZE = 50


CHROME_DRIVER_PATH = './chromedriver'
FIREFOX_DRIVER_PATH = './geckodriver'
FIREFOX_BIN_PATH = '/home/asuka/local/software/firefox/firefox'


def DebugPrint(log):
    print(log)


class StopToken(object):
    pass


class UrlDownloader(object):

    def __init__(self, url):
        self._url = url

    def GetRawData(self):
        ''''''
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
            DebugPrint('Trying to standardize url.')

            new_url = self._StandardizeUrl(self._url)
            DebugPrint('Standardized URL: {}'.format(new_url))

            request = urllib.request.Request(url=new_url, headers=header, method='GET')
            try:
                response = urllib.request.urlopen(request)
            except Exception as e:
                DebugPrint(e)
                DebugPrint('Error URL after standardize:{}'.format(new_url))
                return None
        except Exception as e:
            DebugPrint(e)
            DebugPrint('Error URL: {}'.format(self._url))
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
        browser = webdriver.Chrome(CHROME_DRIVER_PATH, options = options)
        html = ''
        try:
            browser.get(self._url)
            html = browser.page_source
        except Exception as e:
            DebugPrint(e)
        finally:
            browser.quit()
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
            self._LogResult(False)
            return

        downloader = UrlDownloader(self._url)
        raw = downloader.GetRawData()
        if not raw:
            self._LogResult(False)
            return

        with open(self._filename, 'wb') as dst:
            dst.write(raw)

        self._LogResult()

    def _LogResult(self, result=True):
        title = os.path.basename(os.path.dirname(self._filename))
        name = os.path.basename(self._filename)
        if result == True:
            DebugPrint('Downloaded: {} -> {}'.format(title, name))
        else:
            DebugPrint('Failed to download: {} -> {} URL: {}'.format(title, name, self._url))


#producer
class BaseSpider(threading.Thread):

    def __init__(self, entry_queue, job_queue, root_dir):
        super().__init__()
        self._entry_queue = entry_queue
        self._job_queue = job_queue
        self._root_dir = root_dir


    def run(self):
        while True:
            entry_url = self._entry_queue.get()

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

                ext_name = self._GetFileExtFromUrl(img_url)
                filename = '{:04d}{}'.format(idx, ext_name)
                fullname = os.path.join(dir_name, filename)

                job = self._MakeJob(fullname, img_url)
                self._job_queue.put(job)

            self._entry_queue.task_done()


    @staticmethod
    def GetEntryList(url):
        raise Exception('pure virtual method')

    def _GetEntryNameAndPageCount(self, first_url):
        raise Exception('pure virtual method')

    def _GetPageUrlList(self, first_url, page_count):
        raise Exception('pure virtual method')

    #include dot, eg. '.jpg'
    def _GetFileExtFromUrl(self, img_url):
        raise Exception('pure virtual method')

    def _GetImageUrl(self, page_url):
        raise Exception('pure virtual method')

    def _MakeJob(self, filename, url):
        raise Exception('pure virtual method')



class KukuSpider(BaseSpider):

    def __init__(self, entry_queue, job_queue, root_dir):
        super().__init__(entry_queue, job_queue, root_dir)


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

    def _GetFileExtFromUrl(self, img_url):
        _, ext_name = os.path.splitext(img_url)
        return ext_name


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


    def _MakeJob(self, filename, url):
        return DownloadJob(url, filename)



class ManhuaguiSpider(BaseSpider):

    class ManhuaguiDownloadJob(DownloadJob):

        WAIT_IMG_TIMEOUT = 60
        BROWSER_DRIVER_CHROME = 'chrome'
        BROWSER_DRIVER_FIREFOX = 'firefox'
        USING_BROWSER_DRIVER = BROWSER_DRIVER_CHROME

        def __init__(self, url, filename):
            super().__init__(url, filename)


        def Download(self):



            DebugPrint('Downloading URL: {}'.format(self._url))

            if self.USING_BROWSER_DRIVER == self.BROWSER_DRIVER_CHROME:
                self._CreateChromeBrowser()
            elif self.USING_BROWSER_DRIVER == self.BROWSER_DRIVER_FIREFOX:
                self._CreateFirefoxBrowser()
            else:
                DebugPrint('Error: No such browser driver')
                return

            try:
                self._browser.get(self._url)
                try:
                    img = self._browser.find_element_by_id('mangaFile')
                except selenium_exception.NoSuchElementException as e:
                    DebugPrint('Failed to find img element: {}'.format(e))
                    DebugPrint('Try to wait for img element')
                    img = WebDriverWait(self._browser, self.WAIT_IMG_TIMEOUT).until(EC.visibility_of_element_located((By.ID, "mangaFile")))
                self._SavePngFile(img)
            except Exception as e:
                DebugPrint('Error while loading page: {}'.format(e))
            finally:
                self._browser.close()

            self._DestoryBrowser()


        def _CreateChromeBrowser(self):
            options = webdriver.ChromeOptions()
            options.headless = True

            for i in range(0, 5):
                try:
                    self._browser = webdriver.Chrome(CHROME_DRIVER_PATH, options=options)
                    if self._browser:
                        self._browser.set_page_load_timeout(60)
                        break
                except Exception as e:
                    DebugPrint(e)


        def _CreateFirefoxBrowser(self):
            options = webdriver.FirefoxOptions()
            options.headless = True

            for i in range(0, 5):
                try:
                    self._browser = webdriver.Firefox(firefox_binary=FIREFOX_BIN_PATH,
                                                      executable_path=FIREFOX_DRIVER_PATH,
                                                      options=options)
                    if self._browser:
                        break
                except Exception as e:
                    DebugPrint(e)

        def _DestoryBrowser(self):
            if not self._browser:
                return
            try:
                self._browser.quit()
            except Exception as e:
                DebugPrint('Quit browser failed: {}'.format(e))
                try:
                    self._browser.close()
                except Exception as e:
                    DebugPrint('Close browser failed: {}'.format(e))



        def _SavePngFile(self, img_element):
            if not img_element:
                self._LogResult(False)
                return

            if self.USING_BROWSER_DRIVER == self.BROWSER_DRIVER_CHROME:
                self._SaveByChrome(img_element)
            elif self.USING_BROWSER_DRIVER == self.BROWSER_DRIVER_FIREFOX:
                self._SaveByFirefox(img_element)
            else:
                DebugPrint('Error: No such browser driver')



        def _SaveByChrome(self, img_element):
            width = self._browser.execute_script("return Math.max(document.body.scrollWidth, document.body.offsetWidth, document.documentElement.clientWidth, document.documentElement.scrollWidth, document.documentElement.offsetWidth);")
            height = self._browser.execute_script("return Math.max(document.body.scrollHeight, document.body.offsetHeight, document.documentElement.clientHeight, document.documentElement.scrollHeight, document.documentElement.offsetHeight);")
            self._browser.set_window_size(width, height)

            png_data = self._browser.get_screenshot_as_png()
            img = Image.open(BytesIO(png_data))

            location = img_element.location
            size = img_element.size
            left = location['x']
            top = location['y']
            right = location['x'] + size['width']
            bottom = location['y'] + size['height']

            img = img.crop((left, top, right, bottom))
            img.save(self._filename)

            self._LogResult()


        def _SaveByFirefox(self, img_element):

            img_element.screenshot(self._filename)
            self._LogResult()


    def __init__(self, entry_queue, job_queue, root_dir):
        super().__init__(entry_queue, job_queue, root_dir)

    @staticmethod
    def GetEntryList(url):
        html = UrlDownloader(url).GetHtml()
        soup = BeautifulSoup(html, 'html.parser')

        div_capt_list = soup.select('#chapter-list-1')
        if not div_capt_list:
            div_capt_list = soup.select('#chapter-list-0')
            if not div_capt_list:
                return []

        if div_capt_list:
            div_capt_list = div_capt_list[0]

        entry_list = []
        ul_list = div_capt_list.find_all('ul')
        for ul in ul_list:
            a_list = ul.find_all('a', class_='status0')
            for a in a_list:
                path = a.get('href')
                entry_url = urllib.parse.urljoin(url, path)
                entry_list.append(entry_url)

        return entry_list


    def _GetEntryNameAndPageCount(self, first_url):
        html = UrlDownloader(first_url).GetHtml()
        soup = BeautifulSoup(html, 'html.parser')

        a_title = soup.select('body > div.w980.title > div:nth-of-type(2) > h1 > a')[0]
        title = a_title.text

        h2_capt = soup.select('body > div.w980.title > div:nth-of-type(2) > h2')[0]
        capt = h2_capt.text
        entry_name = '{} {}'.format(title, capt)

        span = soup.select('body > div.w980.title > div:nth-of-type(2) > span')[0]
        span_text = span.text

        pat = re.compile('\(/(\d+)\)')
        s = pat.search(span_text)
        if not s:
            DebugPrint("Can not found page count element.")
            return '', 0
        count_text = s.group(1)
        page_count = int(count_text)

        return entry_name, page_count


    def _GetPageUrlList(self, first_url, page_count):
        url_list = []
        for i in range(1, page_count + 1):
            url = '{}#p={}'.format(first_url, i)
            url_list.append(url)
        return url_list

    def _GetFileExtFromUrl(self, img_url):
        return '.png'


    # requires 'Referer' field in http header to download image
    # here we return page url (not image url) to download the entire page
    # using web browser driver later
    def _GetImageUrl(self, page_url):
        # html = UrlDownloader(page_url).GetHtmlByChrome()
        # soup = BeautifulSoup(html, 'html.parse')
        # img = soup.select('#mangaFile')
        # if not img:
        #     DebugPrint('Find img tag failed: {}'.format(page_url))
        #     return ''
        #
        # img_url = img[0].get('src')
        # return img_url
        return page_url



    def _MakeJob(self, filename, url):
        return self.ManhuaguiDownloadJob(url, filename)



class HanhanSpider(BaseSpider):
    pass



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
        if not entry_list:
            DebugPrint('Get entry list failed.')
            return

        job_queue = queue.Queue(N_JOB_QUEUE_SIZE)
        entry_queue = queue.Queue(len(entry_list))


        for entry in entry_list:
            entry_queue.put(entry)


        producer_list = []
        for i in range(0, N_PRODUCER):
            t = self._spider(entry_queue, job_queue, self._root_dir)
            t.start()
            producer_list.append(t)


        customer_list = []
        for i in range(0, N_CUSTOMER):
            t = ComicDownloader(job_queue)
            t.start()
            customer_list.append(t)

        entry_queue.join()
        for i in range(0, N_PRODUCER):
            entry_queue.put(StopToken)

        for t in producer_list:
            t.join()

        job_queue.join()
        for i in range(0, N_CUSTOMER):
            job_queue.put(StopToken)

        for t in customer_list:
            t.join()

        DebugPrint('All jobs done.')





def main():


    # url = 'http://comic.kukudm.com/comiclist/2274/index.htm'
    # manager = SpiderManager(KukuSpider, url, '/home/asuka/local/comic')
    # manager.Process()


    # url = 'https://www.manhuagui.com/comic/14857/'
    url = 'https://www.manhuagui.com/comic/17473/'
    manager = SpiderManager(ManhuaguiSpider, url, '/home/asuka/local/comic/Gabriel')
    manager.Process()



if __name__ == '__main__':
    main()