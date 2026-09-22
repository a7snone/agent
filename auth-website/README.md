# موقع المصادقة (Auth Website)

موقع ويب بسيط بلغة Python/Flask يوفر:

- إنشاء حساب (تحقق من صحة البيانات + كلمات مرور مُشفّرة بـ `werkzeug.security`)
- تسجيل الدخول والخروج عبر جلسات Flask (session)
- تسجيل الدخول / التسجيل عبر جوجل (OAuth 2.0 / OpenID Connect عبر Authlib) — اختياري
- لوحة تحكم محمية لا يمكن الوصول إليها إلا بعد تسجيل الدخول
- قاعدة بيانات SQLite محلية (`auth.db`، تُنشأ تلقائيًا)

## التشغيل

```bash
cd auth-website
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

ثم افتح `http://127.0.0.1:5000` في المتصفح.

## تفعيل تسجيل الدخول عبر جوجل (اختياري)

1. افتح [Google Cloud Console](https://console.cloud.google.com/apis/credentials) وأنشئ مشروعًا جديدًا (أو استخدم موجود).
2. من "OAuth consent screen" فعّل نوع External واملأ الحقول الأساسية (اسم التطبيق، بريد الدعم).
3. من "Credentials" أنشئ "OAuth client ID" من نوع **Web application**، وأضف:

   **للتشغيل المحلي:**
   - Authorized JavaScript origins: `http://127.0.0.1:5000`
   - Authorized redirect URIs: `http://127.0.0.1:5000/oauth/google/callback`

   **للموقع المنشور على fractionksa.com (الموقع مربوط على مسار `/auth/`):**
   - Authorized JavaScript origins: `https://fractionksa.com`
   - Authorized redirect URIs: `https://fractionksa.com/auth/oauth/google/callback`

4. انسخ الـ Client ID والـ Client Secret.

   **محليًا** صدّرهما قبل تشغيل التطبيق:
   ```bash
   export GOOGLE_CLIENT_ID="xxxxxxxx.apps.googleusercontent.com"
   export GOOGLE_CLIENT_SECRET="xxxxxxxx"
   python app.py
   ```

   **للنشر على السيرفر** أضفهما كـ GitHub repository secrets باسم
   `GOOGLE_CLIENT_ID` و `GOOGLE_CLIENT_SECRET` (راجع `deploy/README.md`)،
   ثم شغّل الـ workflow — تُكتب تلقائيًا في `/etc/auth-website.env` على
   السيرفر وتُعاد الخدمة تشغيلها.

إذا لم يتم تعيين المتغيرين، يعمل الموقع بشكل طبيعي بتسجيل الدخول بكلمة المرور فقط، ويختفي زر "الدخول عبر جوجل" تلقائيًا.

عند أول دخول عبر جوجل، يُنشأ حساب جديد تلقائيًا (بدون كلمة مرور) باسم مستخدم مُشتق من البريد الإلكتروني. إذا كان البريد الإلكتروني نفسه مسجّلاً مسبقًا بكلمة مرور، يُربط حساب جوجل بنفس الحساب الموجود.

## ملاحظات أمنية

- غيّر `SECRET_KEY` دائمًا في بيئة الإنتاج (لا تستخدم القيمة الافتراضية).
- الاستعلامات إلى قاعدة البيانات مُعامَلة (parameterized) لمنع SQL injection.
- كلمات المرور لا تُخزَّن أبدًا كنص صريح، فقط كـ hash.
- شغّل الموقع خلف HTTPS في الإنتاج وفعّل `SESSION_COOKIE_SECURE`.
