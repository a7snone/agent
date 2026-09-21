# موقع المصادقة (Auth Website)

موقع ويب بسيط بلغة Python/Flask يوفر:

- إنشاء حساب (تحقق من صحة البيانات + كلمات مرور مُشفّرة بـ `werkzeug.security`)
- تسجيل الدخول والخروج عبر جلسات Flask (session)
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

## ملاحظات أمنية

- غيّر `SECRET_KEY` دائمًا في بيئة الإنتاج (لا تستخدم القيمة الافتراضية).
- الاستعلامات إلى قاعدة البيانات مُعامَلة (parameterized) لمنع SQL injection.
- كلمات المرور لا تُخزَّن أبدًا كنص صريح، فقط كـ hash.
- شغّل الموقع خلف HTTPS في الإنتاج وفعّل `SESSION_COOKIE_SECURE`.
