# مترجم هوشمند EPUB

**🌐 زبانها:** فارسی · [English](README.en.md)

یه وباپ self-hosted که کتاب‌های EPUB انگلیسی رو به فارسی تبدیل می‌کنه — با یک
human-in-the-loop واقعی توی هر مرحلهای که اهمیت داره. کتاب رو آپلود می‌کنید،
glossary اسم‌هاش و اصطلاحات‌ش رو تایید می‌کنید، progress ترجمهی فصل‌به‌فصل رو
زنده می‌بینید، مشکلاتی که AI flag کرده رو بررسی می‌کنید و آخرش یه EPUB فارسی
RTL تمیز دانلود می‌کنید — با همون structure، تصویرها، CSS و فهرست اصلی.

تک‌کاربره، کاملاً روی خودِ سیستم شما اجرا می‌شه، نه اکانتی نه ابری. کلید API
رو خود‌تون می‌ذارید (BYOK) — فقط بابت tokenهایی که واقعاً مصرف می‌شن به
provider پول می‌دید.

## چیکار می‌کنه

1. **آپلود** — یه `.epub` ب‌ندازید؛ همون لحظه title، حجم و تعداد فصل‌ها رو
   می‌بینید، *قبل از* اینکه چیزی ساخته ب‌شه.
2. **Provider** — DeepSeek، OpenAI، Gemini یا هر endpoint سازگار با
   OpenAI (مثل Ollama یا Groq). کلید توی یه فایل کانفیگ محلی روی همون
   دستگاه می‌مونه و هیچ‌جا دیگه‌ای فرستاده نمی‌شه.
3. **Glossary** — اسم‌های کتاب و اصطلاحات تکراری‌ش از اولین فصلِ محتوایی
   استخراج می‌شه؛ فرم فارسی پیشنهادی رو ویرایش می‌کنید و approve می‌زنید.
   از اون به بعد همه‌ی ترجمه‌ها این اسم‌ها رو به‌عنوان ترجمهی ثابت و
   اجباری در نظر می‌گیرن.
4. **ترجمه** — صف ترجمهی کل کتاب در پس‌زمینه با وضعیت زنده‌ی هر فصل.
   خرابیها همی‌شه محدود به همون فصلن: یه فصل failed هیچ‌وقت بقیهی کتاب رو
   بلاک نمی‌کنه و جداگانه retry می‌شه.
5. **بازبینی QA** — یه بررسی اختیاری روی نمونهای از ترجمه‌ها
   (glossary / معنا / روانی / لحن) با متن اصلی و ترجمهی فعلی کنار هم،
   پیشنهاد اصلاح قابل ویرایش، و accept یا keep برای هر مورد.
6. **Finalize** — اصلاحات تایید‌شده اعمال می‌شه، `lang="fa"` و `dir="rtl"`
   روی همه‌ی فصل‌ها ست می‌شه، فونت وزیر‌متن (SIL OFL 1.1، به‌همراه لایسنس‌ش)
   داخل کتاب embed می‌شه، فهرست و عنوان ترجمه می‌شه و EPUB نهایی آماده‌ی
   دانلود می‌شه.

هزینه همی‌شه جلوی چشمته: tokenهای مصرفی هر job، هزینهی تخمینی بر اساس
قیمت provider (جدول داخلی، قابل ویرایش در settings) و تخمین باقیمانده وسط
کار.

## تکنولوژی

- **بک‌اند** — Python 3.11، FastAPI، ebooklib (مدل OPF/spine)،
  BeautifulSoup + lxml (DOM فایل‌های XHTML)، zip surgery با کتابخونهی
  استاندارد
- **فرانت‌اند** — React 18 + Vite (فقط functional components و hooks، CSS
  مینیمال، وضعیت با polling — نه websocket نه فریمورک UI)
- **ذخیرهسازی** — فایلسیستم محلی `data/jobs/<job_id>/`، بدون دیتابیس
- **ترجمه** — هر API سازگار با OpenAI از طریق SDK کتابخونهی `openai`
  (پیش‌تنظیم DeepSeek برای `deepseek-v4-flash` تنظیم شده: thinking خاموش،
  batching آگاه از rate limit، بازیابی پاسخهای خالی)

## نصب و اجرا

به Python 3.10+ (پیشنهاد 3.11) و Node 18+ برای build فرانت‌اند نیاز دارید.

```bash
# 1. بک‌اند
uv venv --python 3.11
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp backend/.env.example backend/.env    # اختیاری: fallback کلید از env

# 2. فرانت‌اند (یه بار build می‌شه؛ خروجی میره توی backend/static)
cd frontend && npm install && npm run build && cd ..

# 3. اجرا
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000
```

مرورگر رو ب‌برید http://127.0.0.1:8000 — توی صفحه‌ی settings provider، مدل و
کلید‌تون رو می‌ذارید (یا از fallback متغیر `DEEPSEEK_API_KEY` استفاده کنید) و
دکمه‌ی «Test connection» با یه درخواست ارزون کلید رو قبل از شروع کتاب
چک می‌کنه.

حالت توسعه‌ی فرانت‌اند (hot reload، پراکسی API به :8000):
`cd frontend && npm run dev`.

## پیکربندی BYOK

| فیلد | توضیح |
|---|---|
| Provider | DeepSeek / OpenAI / Gemini / Custom (base URL سازگار با OpenAI) |
| مدل | انتخابگر per-provider (DeepSeek V4 flash، GPT-4o mini، Gemini 2.5 flash و…) یا متن آزاد برای custom |
| کلید API | توی `data/settings.json` روی دستگاه شما (gitignored، chmod 600)، توی UI ماسک می‌شه و API هیچ‌وقت کامل بر‌نمی‌گردون‌ش |
| قیمت | نرخ input/output به‌ازای هر ۱ میلیون token برای تخمین هزینه — جدول داخلی، قابل ویرایش |

## API

| Method | مسیر | توضیح |
|---|---|---|
| POST | `/preview` | پارس EPUB بدون ساخت job → عنوان، تعداد فصل، تعداد node |
| POST | `/upload` | آپلود `file` (.epub) → `{job_id, report}`؛ استخراج + بازسازی + راستی‌آزمایی |
| GET | `/jobs/{id}` / `/jobs/{id}/status` | اطلاعات کتاب / وضعیت زنده‌ی فصل‌ها + مصرف + هزینه |
| POST | `/glossary/{id}/extract` | پیشنهاد اصطلاحات از اولین فصل محتوایی |
| PATCH | `/glossary/{id}` | ویرایش/تایید glossary با `{glossary: [{original, persian, category, note}]}` |
| POST | `/translate/{id}/chapter/{ch}` | ترجمهی یک فصل (با glossary تایید‌شده) |
| POST | `/translate/{id}/all` | ترجمهی کل کتاب در پس‌زمینه؛ فصل‌های done رد می‌شن |
| POST | `/qa/{id}` · GET `/qa/{id}` · PUT `/qa/{id}/fixes` | اجرا / خواندن / اعمال بازبینی QA |
| POST | `/finalize/{id}` | اصلاحات QA + متادیتا‌ی RTL + فونت + ترجمهی TOC/عنوان → `final.epub` |
| GET | `/download/{id}` | final → translated → rebuilt، به همین ترتیب اولویت |
| GET | `/settings` · PUT · POST `/settings/test` | ذخیره‌ی BYOK (ماسکشده) + تست اتصال |
| GET | `/health` | liveness |

## راستی‌آزمایی (GATE)

هر آپلود قبل از اینکه ترجمه به چیزی دست بزنه یه round-trip کامل اجرا می‌کنه:
EPUB بازسازی‌شده باید دقیقاً مثل نسخه‌ی اصلی رندر ب‌شه —

- فهرست ورودی‌های zip یکسان (با ترتیب)
- همه‌ی ورودی‌های دست‌نخورده (CSS، تصویر، فونت، OPF، NCX، TOC) بایت‌به‌بایت یکسان
- `mimetype` هنوز stored باشه نه deflated (مطابق spec)
- هر فصل بازسازی‌شده XML خوش‌ساخت باشه
- متن ساده‌ی استخراج‌شده فصل‌به‌فصل یکسان (با نرمال‌سازی whitespace)

هر job یک `report.json` داره که هر ۵ تا چک رو ثبت می‌کنه؛ شکست هر کدوم یعنی
شکست همون job.

## تست

```bash
.venv/bin/python -m pytest        # ۶۶ تست: round-trip، مترجم، glossary،
                                  # QA، finalize، settings، preview
```

epubهای واقعی رو ب‌ندازید توی `test-epubs/` (gitignored) — خودکار به‌عنوان
fixtureهای round-trip استفاده می‌شن. `backend/demo.py book.epub` هم از CLI
روی هر فایلی اجرا‌ش می‌کنه.

## ساختار پروژه

```
backend/app/          اپ FastAPI: parser، textnodes، translator، jobs،
                      glossary، qa، finalize، settings، verify، rebuild
backend/static/       فرانت‌اند React ساخته‌شده (سرو‌شده توسط FastAPI)
backend/assets/       فونت وزیر‌متن + لایسنس OFL (embed در finalize)
frontend/             سورس React (Vite)
tests/                ۶۶ تست + سازنده‌ی fixture
data/jobs/<job_id>/   فایل‌های هر job (gitignored)
```

## جاده‌ی پیش رو

پولیش خروجی EPUB3 · تایید دوباره‌ی glossary بعد از ویرایشهای میانه‌ی کتاب ·
workflow CI برای تستها · به‌روزرسانی خودکار قیمت providerها.

## خارج از scope (v1)

چند‌زبانه فراتر از EN→FA · اکانت کاربری / multi-tenant · پرداخت ·
ویرایش گروهی · اپ موبایل.

## لایسنس

MIT — فایل [LICENSE](LICENSE). فونت وزیر‌متن با SIL OFL 1.1.
