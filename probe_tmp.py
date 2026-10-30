import re
import requests

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
}
URLS = [
    "https://www.ic3.gov/AnnualReport/Reports/2024_IC3Report.pdf",
    "https://www.mdpi.com/1099-4300/17/4/2367",
    "https://www.mdpi.com/1099-4300/17/4/2367/pdf",
    "https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2024.1308634/full",
    "https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2024.1308634/pdf",
    "https://www.sciencedirect.com/science/article/pii/S0031320313003282",
    "https://www.usenix.org/conference/usenixsecurity23/presentation/zhou-guangmeng",
]
for u in URLS:
    try:
        r = requests.get(u, headers=H, timeout=30)
        print(u[-55:], r.status_code, r.headers.get("content-type"), r.content[:5], len(r.content))
        if "html" in r.headers.get("content-type", ""):
            print("  meta:", re.findall(r'<meta[^>]*citation_pdf_url[^>]*>', r.text)[:1])
            print("  pdf hrefs:", re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text)[:3])
    except Exception as e:
        print(u[-55:], "ERR", e)
