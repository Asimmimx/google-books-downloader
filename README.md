# Google Books Downloader

Download the preview pages of a Google Books book as high-quality images and a **searchable PDF (OCR)**.

> Only pages that Google Books shows in **full view** or **preview** can be downloaded. If you can't read a page on Google Books, this tool can't get it either.

![Book examples](img.png)

---

## Setup (once)

1. Install **[Python 3.9+](https://www.python.org/downloads/)**. On Windows, tick **"Add Python to PATH"** during setup.
2. Install **[Google Chrome](https://www.google.com/chrome/)**. You don't need to download chromedriver: the right version is fetched automatically.
3. Install the required packages from the project folder:
   ```
   pip install -r requirements.txt
   ```
4. *(Optional, for searchable PDFs)* Install **Tesseract OCR**:
   - Windows: `winget install UB-Mannheim.TesseractOCR` or use the [installer](https://github.com/UB-Mannheim/tesseract/wiki). During setup, tick the extra languages you need (e.g. Turkish).
   - macOS: `brew install tesseract tesseract-lang`
   - Linux: `sudo apt install tesseract-ocr tesseract-ocr-tur`

   Without Tesseract you still get a normal PDF, just without selectable text.

## Usage

### The easy way

- **Windows:** double-click **`start.bat`**.
- **Other systems:** run `python gbd.py`.

Then answer the questions. Press **ENTER** to accept the default shown in `[brackets]`:

| Step | Question | Example answer |
|------|----------|----------------|
| 1 | Link of the book | `https://books.google.com/books?id=buc0AAAAMAAJ` |
| 2 | Which pages | `all` or `1-50` or `1, 10-20, odd` |
| 3 | Where to save | ENTER = the current folder |
| 4 | Make a PDF? Use OCR? Book language? | ENTER, ENTER, `eng` (or `tur`, `deu`, `eng+tur` …) |

When it's done you'll have a folder named after the book containing `page0001.png`, `page0002.png`, … and `<Book title>.pdf`.

### One command

```
python gbd.py "https://books.google.com/books?id=buc0AAAAMAAJ" -p 1-50 -o D:\Books --lang eng
```

| Option | Meaning | Default |
|--------|---------|---------|
| `-p`, `--pages` | Pages to download: `all`, `5`, `10-20`, `odd`, `even`, comma-separated | `all` |
| `-o`, `--output` | Folder to save into | current folder |
| `-l`, `--lang` | Book language for OCR (`eng`, `tur`, `deu`, `fra`, `eng+tur` …) | `eng` |
| `--no-ocr` | Make a plain PDF without searchable text | |
| `--no-pdf` | Only save the images, no PDF | |
| `--show-browser` | Show the Chrome window while scanning | |

Run `python gbd.py --help` for the full list.

### Backups: skip the slow part next time

Scanning a book takes a few minutes, so the list of pages is saved automatically to `backups/<Book title>.json`. Next time, paste that file path instead of the link and the scanning is skipped:

```
python gbd.py "backups/Adventures of Sherlock Holmes - Sir Arthur Conan Doyle.json" -p 100-150
```

Backups from older versions (`Backup of <title>.txt`) still work.

### Turn already-downloaded pages into a PDF

Paste the **folder** instead of a link. The images in it are combined into a PDF (with OCR if available):

```
python gbd.py "D:\Books\My Book" --lang tur
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No preview pages found` | The book has no preview on Google Books. Check that you can read pages in your browser. |
| Some pages are missing | Google only shows part of some books, and only those pages can be downloaded. |
| PDF text isn't selectable | Install Tesseract (see Setup step 4) and make sure the book's language is installed. |
| `OCR language not installed` | Re-run the Tesseract installer and tick that language. |
| Chrome / driver errors | Update Google Chrome and run `pip install -U -r requirements.txt`. |
| Anything else | See `google-books-downloader_crash.log` in the project folder and [open an issue](../../issues). |

---

DISCLAIMER: The code is provided as-is without any warranty. It is intended solely for legal use, such as public-domain books or personal backups that copyright law allows where you live. The authors are not responsible for misuse. See the [License](LICENSE).
