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
- **nginx**: الموقع مربوط على `fractionksa.com/auth/`. إذا لم يوجد أي إعداد
  للدومين مسبقًا، يُنشئ ملف جديد كامل. أما مع الإعداد الموجود فعليًا
  (`/etc/nginx/sites-available/fraction`، يخدم موقع PHP آخر)، فيُضاف فقط
  قسم `location /auth/` بين علامتين مميزتين (`BEGIN/END auth-website /auth`)
  — بقية الملف لا يُمس إطلاقًا. قبل أي تعديل يؤخذ نسخة احتياطية كاملة
  (`fraction.bak.<timestamp>`)، ويُختبر `nginx -t` قبل الـ reload؛ لو فشل
  الاختبار يتم استرجاع النسخة الأصلية تلقائيًا فورًا بدون أي تأثير على
  الموقع الحالي. إعادة النشر لاحقًا تُحدّث نفس القسم فقط (لا يتكرر).

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
