# النشر التلقائي عبر GitHub Actions

كل دفعة (push) على `main` تلمس مجلد `auth-website/` تُشغّل تلقائيًا
`.github/workflows/deploy.yml`، اللي يتصل بالسيرفر عبر SSH وينشر آخر نسخة
من الموقع. يمكن أيضًا تشغيله يدويًا من تبويب **Actions** في GitHub
(زر "Run workflow").

## ماذا يفعل النشر بالضبط

على السيرفر، ينفّذ `deploy/remote_deploy.sh` وهو **آمن للتكرار
(idempotent)** ولا يلمس أي شيء لا يملكه:

- ينشئ/يحدّث بيئة Python الافتراضية ويثبّت المتطلبات + gunicorn
- يولّد `SECRET_KEY` مرة واحدة ويحافظ عليه بين عمليات النشر (`/etc/auth-website.env`)
- يختار منفذًا داخليًا فارغًا تلقائيًا (يبدأ من 8010) ويحفظه (`/etc/auth-website.port`)
- ينشئ خدمة systemd باسم فريد `auth-website.service` فقط — لا يعدّل أي خدمة أخرى
- **لا يلمس nginx إطلاقًا** إذا وجد أي إعداد موجود مسبقًا يذكر `fractionksa.com`؛
  فقط إذا لم يوجد أي إعداد للدومين، ينشئ ملف جديد `auth-website.conf`

## الأسرار (Secrets) المطلوبة

من إعدادات الريبو: **Settings → Secrets and variables → Actions → New repository secret**

| الاسم | القيمة | ملاحظة |
|---|---|---|
| `DEPLOY_HOST` | `157.245.144.18` | |
| `DEPLOY_USER` | `root` | |
| `DEPLOY_SSH_KEY` | (محتوى المفتاح الخاص كاملاً) | يُعطى لك منفصلاً — لا تضعه في الكود أبدًا |
| `DEPLOY_PORT` | `22` | اختياري، الافتراضي 22 |
| `DEPLOY_PATH` | `/opt/apps/auth-website/app` | اختياري، هذا هو الافتراضي |
| `GOOGLE_CLIENT_ID` | — | اختياري لتفعيل تسجيل الدخول عبر جوجل |
| `GOOGLE_CLIENT_SECRET` | — | اختياري لتفعيل تسجيل الدخول عبر جوجل |

بعد إضافة الأسرار، أي دفعة جديدة على `main` (أو تشغيل يدوي من Actions)
تنشر الموقع تلقائيًا.
