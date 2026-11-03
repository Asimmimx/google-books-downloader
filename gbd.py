"""
Google Books Downloader
Downloads the preview pages of a Google Books book as images (and a PDF).

Interactive:   python gbd.py
One command:   python gbd.py "<book URL, ID or backup file>" [-p PAGES] [-o FOLDER] [--lang eng] [--no-ocr] [--no-pdf]
PDF only:      python gbd.py "<folder with page images>" [--lang eng]
"""
import os
import ast
import sys
import json
import shutil
import argparse
import tempfile
import traceback
import subprocess
from concurrent.futures import ThreadPoolExecutor
import regex as re
import requests
from time import sleep
from progressbar import progressbar as bar

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(HERE, "backups")
CRASH_LOG = os.path.join(HERE, "google-books-downloader_crash.log")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# page image URLs look like ...books/content?id=X&pg=PA12&img=1&zoom=3&hl=en&sig=Y&w=1280
PAGE_URL_RE = re.compile(r"(https://[^\s\"']+content[^\s\"']+pg=[A-Z]+([0-9]+)[^\s\"']*?)(&w=[0-9]+)")
BOOK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12}$")

PAGES_HELP = """Which pages do you want?
  all          every page that has a preview
  5, 3, 16     exact page numbers
  11-13        a range
  odd / even   odd or even pages
  Combine them with commas, e.g.  1, 10-50, odd"""


# ---------------------------------------------------------------- helpers

def ask(question, default=None):
    """Asks a question; ENTER returns the default."""
    hint = f" [{default}]" if default else ""
    answer = input(f"\n{question}{hint}\n> ").strip().strip('"').strip("'")
    return answer or (default or "")


def ask_yes_no(question, default=True):
    while True:
        answer = ask(question, "Y/n" if default else "y/N").lower()
        if answer == "y/n":  # ENTER pressed
            return default
        if answer in ("y", "yes", "e", "evet"):
            return True
        if answer in ("n", "no", "h", "hayir", "hayır"):
            return False
        print("Please type y or n.")


def safe_filename(name):
    """Removes characters Windows doesn't allow in file/folder names."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name[:150] or "book"


def describe_pages(numbers):
    """[1, 2, 3, 7, 9, 10] -> '1-3, 7, 9-10'"""
    numbers = sorted(numbers)
    parts, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            parts.append(str(start) if start == n else f"{start}-{n}")
            start = None
    return ", ".join(parts)


def parse_book_id(text):
    """Accepts a Google Books URL or a bare book ID."""
    ids = re.findall(r"[?&]id=([A-Za-z0-9_-]+)", text)
    if ids:
        return ids[-1]
    if BOOK_ID_RE.match(text):
        return text
    return None


# ---------------------------------------------------------------- browser

def start_browser(show=False):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if not show:
        options.add_argument("--headless=new")
    options.add_argument("--log-level=3")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    # Selenium downloads a chromedriver matching the installed Chrome by itself
    return webdriver.Chrome(options=options)


def get_title(driver, book_id):
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import WebDriverException

    driver.get(f"https://books.google.com/books?id={book_id}&hl=en")
    sleep(2)
    try:
        title = driver.find_element(By.CLASS_NAME, "gb-volume-title").text
    except WebDriverException:
        title = driver.title.replace(" - Google Books", "").strip()
    try:
        author = driver.find_element(By.CLASS_NAME, "addmd").text
        if author.lower().startswith("by"):
            author = author[2:].strip()
    except WebDriverException:
        author = ""
    return safe_filename(f"{title} (by {author})" if author else title or book_id)


def collect_urls(driver, found):
    """Reads Chrome's network log and adds page image URLs to `found`."""
    for entry in driver.get_log("performance"):
        try:
            msg = json.loads(entry["message"])["message"]
        except (KeyError, ValueError):
            continue
        if msg.get("method") != "Network.requestWillBeSent":
            continue
        url = msg.get("params", {}).get("request", {}).get("url", "")
        for full, number, _ in PAGE_URL_RE.findall(url):
            # a huge width makes Google send the biggest image it has
            found.setdefault(int(number), full + "&w=69420")


def scan_pages(driver, book_id):
    """Scrolls through the whole book, returns {page number: image URL}."""
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import WebDriverException

    driver.get(f"https://books.google.com/books?id={book_id}&pg=1&hl=en&f=false"
               "&output=embed&source=gbs_embed")
    sleep(3)
    found, stale_rounds = {}, 0

    while stale_rounds < 3:
        before = len(found)
        try:
            driver.find_element(By.CLASS_NAME, "pageImageDisplay").click()
        except WebDriverException:
            pass
        body = driver.find_element(By.TAG_NAME, "body")
        for _ in range(25):
            body.send_keys(Keys.SPACE)
            sleep(0.1)
        sleep(2)
        collect_urls(driver, found)
        print(f"\r  {len(found)} pages found...", end="", flush=True)
        stale_rounds = stale_rounds + 1 if len(found) == before else 0

    print()
    return found


def get_cookies(driver, url):
    """Google only serves page images to a 'real' browser session."""
    driver.get(url)
    sleep(1)
    return {c["name"]: c["value"] for c in driver.get_cookies()}


# ---------------------------------------------------------------- backups

def save_backup(title, pages):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{title}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"title": title, "pages": pages}, f, ensure_ascii=False, indent=1)
    return path


def load_backup(path):
    """Reads a backup (new .json or old 'Backup of X.txt' format)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = json.loads(text)
        return data["title"], {int(k): v for k, v in data["pages"].items()}
    except (ValueError, KeyError, TypeError):
        name = os.path.splitext(os.path.basename(path))[0]
        if name.startswith("Backup of "):
            name = name[len("Backup of "):]
        return safe_filename(name), ast.literal_eval(text)


# ---------------------------------------------------------------- pages

def select_pages(user_input, all_pages):
    """Returns only the pages the user asked for. Raises ValueError on bad input."""
    tokens = [t for t in user_input.replace(" ", "").lower().split(",") if t]
    if not tokens:
        raise ValueError
    if "all" in tokens:
        return dict(sorted(all_pages.items()))

    selected = {}
    for token in tokens:
        if token == "odd":
            selected.update({k: v for k, v in all_pages.items() if k % 2})
        elif token == "even":
            selected.update({k: v for k, v in all_pages.items() if k % 2 == 0})
        elif "-" in token:
            a, b = map(int, token.split("-"))
            selected.update({k: v for k, v in all_pages.items() if min(a, b) <= k <= max(a, b)})
        else:
            n = int(token)
            if n in all_pages:
                selected[n] = all_pages[n]
    return dict(sorted(selected.items()))


def download_pages(pages, cookies, folder):
    """Downloads the images, returns the list of saved files in page order."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.cookies.update(cookies)
    saved, failed = [], []

    for number, url in bar(list(pages.items())):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            ext = ".jpg" if "jpeg" in response.headers.get("Content-Type", "") else ".png"
            path = os.path.join(folder, f"page{number:04d}{ext}")
            with open(path, "wb") as f:
                f.write(response.content)
            saved.append(path)
        except requests.RequestException:
            failed.append(number)

    if failed:
        print(f"  Could not download pages: {describe_pages(failed)}")
    return saved


def find_images(folder):
    """Page images in a folder, in page order."""
    files = [f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    key = lambda f: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", f.lower())]
    return [os.path.join(folder, f) for f in sorted(files, key=key)]


def make_pdf(images, pdf_path):
    """Plain PDF: just the page images, no selectable text."""
    from PIL import Image

    pages = []
    for path in images:
        im = Image.open(path)
        pages.append(im if im.mode in ("RGB", "L") else im.convert("RGB"))
    pages[0].save(pdf_path, save_all=True, append_images=pages[1:], resolution=150)


def find_tesseract():
    """Path of tesseract.exe, or None if Tesseract OCR isn't installed."""
    found = shutil.which("tesseract")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        path = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
        if os.path.isfile(path):
            return path
    return None


def tesseract_languages(tesseract):
    out = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True).stdout
    return {line.strip() for line in out.splitlines()[1:] if line.strip()}


def make_ocr_pdf(images, pdf_path, tesseract, lang):
    """Searchable PDF: page images with an invisible text layer made by Tesseract."""
    from pypdf import PdfWriter

    tmp = tempfile.mkdtemp(prefix="gbd-ocr-")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")  # we run several pages in parallel

    def ocr_page(i_path):
        i, path = i_path
        base = os.path.join(tmp, f"{i:05d}")
        subprocess.run([tesseract, path, base, "-l", lang, "pdf"], env=env,
                       capture_output=True, check=True)
        return base + ".pdf"

    try:
        workers = max(1, (os.cpu_count() or 2) - 1)
        with ThreadPoolExecutor(workers) as pool:
            parts = list(bar(pool.map(ocr_page, enumerate(images)), max_value=len(images)))
        writer = PdfWriter()
        for part in parts:
            writer.append(part)
        with open(pdf_path, "wb") as f:
            writer.write(f)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_pdf(images, pdf_path, ocr_lang):
    """Makes a searchable PDF if OCR is wanted and possible, otherwise a plain one."""
    if ocr_lang:
        tesseract = find_tesseract()
        if not tesseract:
            print("Tesseract OCR is not installed, so the PDF won't have searchable text.\n"
                  "To get OCR, install it with:  winget install UB-Mannheim.TesseractOCR")
        else:
            missing = [l for l in ocr_lang.split("+") if l not in tesseract_languages(tesseract)]
            if missing:
                print(f"OCR language(s) not installed: {', '.join(missing)}. Making a PDF without OCR.")
            else:
                print(f"Creating a searchable PDF (OCR, language: {ocr_lang})...")
                make_ocr_pdf(images, pdf_path, tesseract, ocr_lang)
                return
    print("Creating the PDF...")
    make_pdf(images, pdf_path)


# ---------------------------------------------------------------- main flow

def main():
    parser = argparse.ArgumentParser(
        description="Download the preview pages of a Google Books book.",
        epilog='Example: python gbd.py "https://books.google.com/books?id=buc0AAAAMAAJ" -p 1-20')
    parser.add_argument("book", nargs="?", help="book URL, book ID, a backup file, or a folder of page images (PDF only)")
    parser.add_argument("-p", "--pages", help='pages to download, e.g. "all" or "1, 10-50, odd" (default: all)')
    parser.add_argument("-o", "--output", help="folder to save into (default: current folder)")
    parser.add_argument("--no-pdf", action="store_true", help="don't combine the pages into a PDF")
    parser.add_argument("--no-ocr", action="store_true", help="make a plain PDF without searchable text")
    parser.add_argument("-l", "--lang", default="eng",
                        help='book language for OCR, e.g. eng, tur, deu, or "eng+tur" (default: eng)')
    parser.add_argument("--show-browser", action="store_true", help="show the Chrome window while scanning")
    args = parser.parse_args()
    interactive = args.book is None

    print("\n=== Google Books Downloader ===")
    if interactive:
        print("Tip: press ENTER to accept the answer shown in [brackets].")

    # 1. which book?
    source = args.book
    while True:
        if source is None:
            source = ask("Step 1/4 - Paste the Google Books link of the book.\n"
                         "(You can also paste a backup file from an earlier download,\n"
                         " or a folder of downloaded pages to only turn it into a PDF.)")
        if os.path.isdir(source):
            return folder_to_pdf(source, args, interactive)
        if os.path.isfile(source):
            title, all_pages = load_backup(source)
            book_id = None
            print(f"\nLoaded backup of \"{title}\".")
            break
        book_id = parse_book_id(source)
        if book_id:
            break
        print("That doesn't look like a Google Books link. It should contain \"id=...\".")
        if not interactive:
            return 1
        source = None

    driver = None
    try:
        print("\nStarting Chrome in the background...")
        driver = start_browser(args.show_browser)

        if book_id:
            title = get_title(driver, book_id)
            print(f"Book: {title}")
            print("Scanning the preview pages. This can take a few minutes...")
            all_pages = scan_pages(driver, book_id)
            if not all_pages:
                print("\nNo preview pages found. This book probably has no preview on Google Books.")
                return 1
            backup = save_backup(title, all_pages)
            print(f"Progress saved to: {backup}\n(Next time you can paste this file path instead of the link.)")

        print(f"\nPages with preview ({len(all_pages)}): {describe_pages(all_pages)}")

        # 2. which pages?
        choice = args.pages
        while True:
            if choice is None:
                choice = ask("Step 2/4 - " + PAGES_HELP, "all")
            try:
                selected = select_pages(choice, all_pages)
                if selected:
                    break
                print("None of those pages have a preview. Please pick from the list above.")
            except ValueError:
                print(f"Couldn't understand \"{choice}\".")
            if not interactive:
                return 1
            choice = None

        # 3. where to?
        output = args.output
        while True:
            if output is None:
                output = os.getcwd() if not interactive else \
                    ask("Step 3/4 - Where should the book be saved? (a new folder will be created there)", os.getcwd())
            folder = os.path.join(os.path.expanduser(output), title)
            try:
                os.makedirs(folder, exist_ok=True)
                break
            except OSError:
                print(f"Can't create a folder in \"{output}\".")
                if not interactive:
                    return 1
                output = None

        # 4. pdf?
        want_pdf, ocr_lang = pdf_options(args, interactive, "Step 4/4 - ")

        print(f"\nDownloading {len(selected)} pages...")
        cookies = get_cookies(driver, next(iter(selected.values())))
        images = download_pages(selected, cookies, folder)
    finally:
        if driver:
            driver.quit()

    if not images:
        print("\nNo pages could be downloaded. Please try again later.")
        return 1

    print(f"\nDone! {len(images)} pages saved in:\n  {folder}")
    if want_pdf:
        pdf_path = os.path.join(folder, f"{title}.pdf")
        build_pdf(images, pdf_path, ocr_lang)
        print(f"PDF: {pdf_path}")
    return 0


def pdf_options(args, interactive, prefix="", ask_pdf=True):
    """Returns (make a PDF?, OCR language or None)."""
    want_pdf = not args.no_pdf
    ocr_lang = None if args.no_ocr else args.lang
    if not interactive:
        return want_pdf, ocr_lang

    want_pdf = ask_yes_no(prefix + "Combine the pages into a single PDF?", True) if ask_pdf else True
    if not want_pdf:
        return False, None
    if not find_tesseract():
        print("(Tesseract OCR isn't installed, so the PDF won't have searchable text.\n"
              " To add OCR later, install it with:  winget install UB-Mannheim.TesseractOCR)")
        return True, None
    if not ask_yes_no("Make the PDF text searchable and copyable (OCR)?", True):
        return True, None
    installed = tesseract_languages(find_tesseract())
    while True:
        lang = ask("Language of the book? (eng = English, tur = Turkish, deu = German,\n"
                   "fra = French, ... several: eng+tur)", args.lang).lower()
        missing = [l for l in lang.split("+") if l not in installed]
        if not missing:
            return True, lang
        print(f"Unknown or not installed language: {', '.join(missing)}. "
              "Use 3-letter codes like eng, tur, deu.")


def folder_to_pdf(folder, args, interactive):
    """Turns an existing folder of page images into a PDF."""
    images = find_images(folder)
    if not images:
        print(f"No page images (.png/.jpg) found in \"{folder}\".")
        return 1
    print(f"\nFound {len(images)} page images in \"{folder}\".")
    args.no_pdf = False
    _, ocr_lang = pdf_options(args, interactive, ask_pdf=False)
    pdf_path = os.path.join(folder, safe_filename(os.path.basename(os.path.normpath(folder))) + ".pdf")
    build_pdf(images, pdf_path, ocr_lang)
    print(f"PDF: {pdf_path}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        code = 1
    except Exception:
        with open(CRASH_LOG, "w", encoding="utf-8") as log:
            log.write(traceback.format_exc())
        print(f"""
Something went wrong :/
Please check that:
  - you are connected to the Internet
  - Google Chrome is installed
  - the book has a preview on Google Books

Error details were saved to:
  {CRASH_LOG}
You can report the problem at github.com/aprikyan/google-books-downloader/issues""")
        code = 1

    if len(sys.argv) == 1:  # keep the window open when double-clicked
        try:
            input("\nPress ENTER to close.")
        except EOFError:
            pass
    sys.exit(code)
