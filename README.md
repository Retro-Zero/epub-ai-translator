# مترجم هوشمند EPUB

**🌐 زبان‌ها:** فارسی · [English](README.en.md)

یک وب‌اپ **self-hosted** برای ترجمه‌ی کتاب‌های EPUB انگلیسی به فارسی، با یک **human-in-the-loop** واقعی در مراحل مهم.

کتاب را آپلود می‌کنید، ساختارش را قبل از شروع می‌بینید، Glossary اسم‌ها و اصطلاحات را بررسی و تأیید می‌کنید، ترجمه را فصل‌به‌فصل با progress زنده دنبال می‌کنید، خروجی را در مرحله‌ی QA بررسی می‌کنید و در نهایت یک EPUB فارسی RTL تحویل می‌گیرید.

ساختار اصلی کتاب، تصاویر، CSS و فهرست آن حفظ می‌شوند.

> **کاملاً local و تک‌کاربره:** بدون account، بدون cloud و بدون database.
> **BYOK:** API key خودتان را استفاده می‌کنید و فقط هزینه‌ی tokenهای مصرف‌شده را به provider می‌پردازید.

---

## ✨ قابلیت‌ها

### ۱. آپلود و بررسی EPUB

فایل `.epub` را آپلود کنید و قبل از اینکه چیزی ساخته یا ترجمه شود، اطلاعات اولیه‌ی کتاب را ببینید:

* عنوان
* حجم فایل
* تعداد فصل‌ها
* تعداد content nodeها

### ۲. اتصال به Provider دلخواه

می‌توانید از این providerها استفاده کنید:

* DeepSeek
* OpenAI
* Gemini
* هر endpoint سازگار با OpenAI، مثل Ollama یا Groq

API key به‌صورت local روی دستگاه شما ذخیره می‌شود و به هیچ سرویس دیگری ارسال نمی‌شود.

قبل از شروع ترجمه هم می‌توانید با یک درخواست ارزان، اتصال و API key را تست کنید.

### ۳. Glossary با تأیید کاربر

اسم شخصیت‌ها و اصطلاحات تکرارشونده از اولین فصل محتوایی استخراج می‌شوند.

AI برای هر مورد یک ترجمه‌ی فارسی پیشنهاد می‌دهد و شما می‌توانید:

* ترجمه را تغییر دهید
* یادداشت اضافه کنید
* مورد را تأیید کنید

بعد از تأیید، این موارد به‌عنوان ترجمه‌های **ثابت و اجباری** در تمام ترجمه‌های کتاب استفاده می‌شوند.

### ۴. ترجمه‌ی فصل‌به‌فصل

ترجمه‌ی کل کتاب در پس‌زمینه انجام می‌شود و progress هر فصل به‌صورت زنده نمایش داده می‌شود.

اگر یک فصل fail شود:

* بقیه‌ی کتاب متوقف نمی‌شود
* مشکل همان فصل باقی می‌ماند
* امکان retry همان فصل وجود دارد

Batchها هم با محدودیت concurrency و rate limit اجرا می‌شوند.

### ۵. بازبینی QA

یک مرحله‌ی اختیاری برای بررسی کیفیت و consistency ترجمه وجود دارد.

نمونه‌ای از ترجمه‌ها از نظر موارد زیر بررسی می‌شوند:

* استفاده از Glossary
* انتقال معنا
* روان بودن فارسی
* لحن

متن اصلی و ترجمه کنار هم نمایش داده می‌شوند و برای مشکلات پیدا‌شده، پیشنهاد اصلاح قابل ویرایش ارائه می‌شود.

در نهایت می‌توانید هر پیشنهاد را **Accept** یا **Keep** کنید.

### ۶. Finalize

در مرحله‌ی نهایی:

* اصلاحات تأییدشده اعمال می‌شوند
* `lang="fa"` و `dir="rtl"` تنظیم می‌شوند
* فونت **Vazirmatn** داخل EPUB embed می‌شود
* لایسنس SIL OFL 1.1 فونت نیز همراه کتاب قرار می‌گیرد
* عنوان و TOC ترجمه می‌شوند
* EPUB نهایی آماده‌ی دانلود می‌شود

ساختار اصلی کتاب، تصاویر، CSS و TOC حفظ می‌شوند.

---

## 💰 هزینه‌ی ترجمه

هزینه‌ی مصرف‌شده در هر job داخل برنامه نمایش داده می‌شود.

همچنین می‌توانید:

* tokenهای مصرف‌شده را ببینید
* هزینه‌ی تخمینی را بر اساس قیمت provider مشاهده کنید
* هزینه‌ی احتمالی باقی‌مانده را حین ترجمه ببینید
* قیمت input/output هر provider را در Settings تغییر دهید

---

## 🛡️ Round-trip Fidelity Gate

قبل از اینکه ترجمه به محتوای کتاب دست بزند، EPUB یک **round-trip verification** کامل را پشت سر می‌گذارد.

EPUB بازسازی‌شده باید از نظر ساختار و محتوای دست‌نخورده، با فایل اصلی مطابقت داشته باشد.

این Gate موارد زیر را بررسی می‌کند:

* ترتیب ورودی‌های ZIP یکسان باشد
* فایل‌های دست‌نخورده مثل CSS، تصاویر، فونت، OPF، NCX و TOC دقیقاً یکسان باشند
* `mimetype` همچنان `stored` باشد و deflate نشده باشد
* تمام فصل‌های بازسازی‌شده XML معتبر داشته باشند
* متن ساده‌ی هر فصل قبل و بعد از rebuild یکسان باشد (با نرمال‌سازی whitespace)

برای هر job یک `report.json` ساخته می‌شود که نتیجه‌ی هر ۵ بررسی را ثبت می‌کند.

اگر هر کدام از این تست‌ها fail شود، job متوقف می‌شود.

---

## 🧠 مقاومت در برابر رفتارهای عجیب مدل

مدل‌های زبانی همیشه دقیقاً همان چیزی را که انتظار داریم برنمی‌گردانند.

Translator برای بعضی از خطاهای رایج recovery دارد؛ مثلاً وقتی مدل:

* برای یک node پاسخ خالی برمی‌گرداند
* بعضی آیتم‌های یک batch را جا می‌اندازد
* پاسخ ناقص برمی‌گرداند

در این شرایط، nodeهای مشکل‌دار می‌توانند متن اصلی خودشان را حفظ کنند و ترجمه‌ی فصل ادامه پیدا کند، به‌جای اینکه کل کتاب fail شود.

---

## 🧰 تکنولوژی

### Backend

* Python 3.11
* FastAPI
* ebooklib
* BeautifulSoup
* lxml
* ZIP manipulation با standard library

### Frontend

* React 18
* Vite
* Functional Components + Hooks
* CSS مینیمال
* Polling برای وضعیت job
* بدون WebSocket
* بدون UI framework

### Storage

تمام داده‌ها local ذخیره می‌شوند:

```text
data/jobs/<job_id>/
```

هیچ databaseای استفاده نمی‌شود.

### Translation

ترجمه از طریق SDK کتابخانه‌ی `openai` انجام می‌شود و با APIهای سازگار با OpenAI کار می‌کند.

Preset فعلی DeepSeek برای `deepseek-v4-flash` تنظیم شده و شامل:

* batching
* rate-limit awareness
* concurrency محدود
* recovery پاسخ‌های خالی

است.

---

## 🚀 نصب و اجرا

### پیش‌نیازها

* Python 3.10+ (پیشنهاد: 3.11)
* Node.js 18+

### ۱. نصب Backend

```bash
uv venv --python 3.11
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp backend/.env.example backend/.env
```

فایل `.env` اختیاری است و می‌توانید از آن برای fallback API key استفاده کنید.

### ۲. Build کردن Frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

خروجی build داخل `backend/static` قرار می‌گیرد.

### ۳. اجرای برنامه

```bash
cd backend
../.venv/bin/uvicorn app.main:app --port 8000
```

بعد مرورگر را باز کنید:

```text
http://127.0.0.1:8000
```

از Settings می‌توانید Provider، مدل و API key را تنظیم کنید.

قبل از شروع ترجمه، دکمه‌ی **Test connection** یک درخواست ارزان برای بررسی اتصال اجرا می‌کند.

### Development mode

برای اجرای Frontend با hot reload:

```bash
cd frontend
npm run dev
```

---

## 🔑 BYOK Configuration

| گزینه        | توضیح                                                       |
| ------------ | ----------------------------------------------------------- |
| **Provider** | DeepSeek / OpenAI / Gemini / Custom                         |
| **Model**    | مدل پیشنهادی برای هر provider یا مقدار دلخواه برای Custom   |
| **API Key**  | در `data/settings.json` روی دستگاه شما ذخیره می‌شود         |
| **Pricing**  | نرخ input/output به‌ازای هر ۱ میلیون token برای تخمین هزینه |

API key:

* روی سیستم خودتان باقی می‌ماند
* در UI به‌صورت mask نمایش داده می‌شود
* به‌صورت کامل از API برگردانده نمی‌شود
* فایل تنظیمات با `gitignore` محافظت می‌شود
* با `chmod 600` محدود می‌شود

---

## 🔌 API

| Method  | Endpoint                       | توضیح                                     |
| ------- | ------------------------------ | ----------------------------------------- |
| `POST`  | `/preview`                     | Parse کردن EPUB بدون ساخت job             |
| `POST`  | `/upload`                      | آپلود EPUB و اجرای rebuild + verification |
| `GET`   | `/jobs/{id}`                   | اطلاعات job                               |
| `GET`   | `/jobs/{id}/status`            | وضعیت فصل‌ها، token و هزینه               |
| `POST`  | `/glossary/{id}/extract`       | استخراج Glossary                          |
| `PATCH` | `/glossary/{id}`               | ویرایش و تأیید Glossary                   |
| `POST`  | `/translate/{id}/chapter/{ch}` | ترجمه‌ی یک فصل                            |
| `POST`  | `/translate/{id}/all`          | ترجمه‌ی کل کتاب                           |
| `POST`  | `/qa/{id}`                     | اجرای QA                                  |
| `GET`   | `/qa/{id}`                     | دریافت نتایج QA                           |
| `PUT`   | `/qa/{id}/fixes`               | اعمال تصمیم‌های QA                        |
| `POST`  | `/finalize/{id}`               | ساخت EPUB نهایی                           |
| `GET`   | `/download/{id}`               | دانلود خروجی نهایی                        |
| `GET`   | `/settings`                    | دریافت تنظیمات                            |
| `PUT`   | `/settings`                    | ذخیره‌ی تنظیمات                           |
| `POST`  | `/settings/test`               | تست اتصال به provider                     |
| `GET`   | `/health`                      | Health check                              |

---

## 🧪 تست

```bash
.venv/bin/python -m pytest
```

در حال حاضر **۶۶ تست** وجود دارد که بخش‌هایی مثل این‌ها را پوشش می‌دهند:

* Round-trip verification
* Translator
* Glossary
* QA
* Finalize
* Settings
* Preview

برای استفاده از EPUBهای واقعی به‌عنوان fixture:

```text
test-epubs/
```

این پوشه `gitignored` است.

همچنین می‌توانید rebuild را از CLI روی یک EPUB اجرا کنید:

```bash
python backend/demo.py book.epub
```

---

## 📁 ساختار پروژه

```text
backend/
├── app/
│   ├── parser
│   ├── textnodes
│   ├── translator
│   ├── jobs
│   ├── glossary
│   ├── qa
│   ├── finalize
│   ├── settings
│   ├── verify
│   └── rebuild
├── static/          # Frontend build
└── assets/          # Vazirmatn + OFL license

frontend/             # React + Vite source
tests/                # 66 tests + fixtures

data/
└── jobs/<job_id>/    # Job data (gitignored)
```

---

## 🗺️ Roadmap

* پولیش بیشتر خروجی EPUB3
* تأیید دوباره‌ی Glossary بعد از تغییرات میانه‌ی کتاب
* CI workflow برای اجرای خودکار تست‌ها
* به‌روزرسانی خودکار قیمت providerها

---

## 🚫 خارج از Scope نسخه‌ی فعلی

فعلاً این موارد جزو پروژه نیستند:

* ترجمه‌ی چندزبانه فراتر از EN → FA
* User accounts
* Multi-tenancy
* پرداخت
* Bulk editing
* اپلیکیشن موبایل

---

## 📄 License

این پروژه تحت **MIT License** منتشر شده است.

* کد پروژه: MIT
* فونت Vazirmatn: **SIL Open Font License 1.1**

جزئیات در فایل [LICENSE](LICENSE).
