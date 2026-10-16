import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


def http_get(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,fa;q=0.8,ru;q=0.7,zh;q=0.6"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")
