# Firebase Cloud Firestore

## حالة الربط

يوجد تنفيذ مستقل لواجهات النظام يخزن المستخدمين والملفات والبيانات الأكاديمية والتبليغات والتأكيدات والجداول وسجل العمليات في **مجموعات Firestore** عند ضبط `DATABASE_BACKEND=firestore`. لا يستخدم PostgreSQL أو SQLite مرآة تخزين في هذا الوضع. ملفات المرفقات وحدها تبقى في تخزين الخادم المحلي المحمي.

أُنشئ المشروع `BA-DMS Mosul` بمعرّف `ba-dms-mosul` وتحقق ظهور Spark في لوحة Firebase. لم يُفعّل اتصال الخادم بعد: اعتماد الخدمة لم يُجهّز، وتعذر تثبيت `firebase-admin` في بيئة التنفيذ الحالية. اختبارات عقد الواجهات تعمل على بديل ذاكرة صريح، ولا تثبت نجاح SDK أو IAM أو قواعد الأمان أو معاملات Firestore الفعلية. لا تعلن الخدمة نجاح اتصال عند غياب الإعدادات؛ تفشل بوضوح بدل الرجوع إلى قاعدة محلية صامتة.

## الخطة المجانية

استخدم Spark ولا تربط حساب فوترة. الحصة المجانية الحالية لقاعدة واحدة تشمل 1 GiB و50,000 قراءة و20,000 كتابة يوميًا؛ راقب الاستخدام. تستهلك معاملات هذا التنفيذ قراءات للمجموعات المعنية للتحقق من العلاقات، لذلك الحصة ليست ضمانًا لتغطية أي حجم استخدام. لا تستخدم Cloud Functions أو App Hosting أو SQL Connect هنا.

Cloud Storage يتطلب Blaze المرتبط بالفوترة حاليًا، ولذلك لم يستخدم. ملفات PDF والصور تحفظ على خادم الجامعة/الجهاز في `UPLOAD_DIR` مع حماية API. Firebase ليس استضافة مجانية لمحرك Python وOR-Tools؛ يبقى الخادم المحلي أو خادم الجامعة مطلوبًا.

المراجع الرسمية: [حصص Firestore](https://firebase.google.com/docs/firestore/quotas)، [خطط Firebase](https://firebase.google.com/docs/projects/billing/firebase-pricing-plans)، [اشتراط Blaze للتخزين](https://firebase.google.com/docs/storage/faqs-storage-changes-announced-sept-2024)، [تهيئة Admin SDK](https://firebase.google.com/docs/admin/setup).

## إعداد المشروع

1. أنشئ أو اختر مشروع Firebase بحسابك وعلى Spark، وأنشئ قاعدة Cloud Firestore الافتراضية Standard وحدد منطقتها المناسبة. لا تستخدم رابط كروب أو ملف Excel بوصفه إعداد اتصال.
2. احتفظ بـProject ID. لا تكفي مفاتيح إعداد تطبيق الويب لمنح الخادم وصولًا إداريًا.
3. جهّز اعتماد خدمة على جهاز الخادم بحسب تعليمات Firebase الرسمية، واحفظ ملف JSON خارج الشفرة. لا ترفعه للمحادثة أو الواجهة. يحتاج حساب الخدمة صلاحيات IAM مناسبة للقراءة والكتابة في Firestore.
4. طبّق `firebase/firestore.rules` الذي يمنع وصول المتصفح المباشر. Admin SDK يعمل عبر IAM ولا يعتمد على هذه القواعد؛ صلاحيات FastAPI تظل إلزامية. لا تفتح القواعد بـ`allow read, write: if true`.
5. لا تمكّن فوترة أو خدمات إضافية لتنفيذ هذا المشروع.

## التشغيل المحلي مع Firestore

من backend، بعد إنشاء بيئة Python:

```powershell
python -m pip install -r requirements-firebase.txt
$env:DATABASE_BACKEND = 'firestore'
$env:FIREBASE_PROJECT_ID = 'your-real-project-id'
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:/secure/firebase-admin.json'
$env:JWT_SECRET = 'choose-a-unique-random-secret-at-least-32-characters'
$env:UPLOAD_DIR = 'C:/secure/ba-dms-uploads'
$env:ADMIN_PASSWORD = 'choose-a-unique-administrator-password'
```

إن كانت قاعدة الوجهة جديدة وفارغة:

```powershell
python -m app.firebase_init
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

ثم شغّل واجهة React كالمعتاد. الحساب `admin`. التوثيق هنا يستخدم JWT الخاص بالنظام مع إبطال الجلسات؛ لا يدّعي استخدام Firebase Authentication أو تسجيل Google.

## Docker

أضف إلى `.env`:

```dotenv
FIREBASE_PROJECT_ID=your-real-project-id
FIREBASE_SERVICE_ACCOUNT_FILE=C:/secure/firebase-admin.json
```

مع `JWT_SECRET` و`ADMIN_PASSWORD` العشوائيين، ثم:

```powershell
docker compose -f compose.firebase.yaml up -d --build
docker compose -f compose.firebase.yaml exec backend python -m app.firebase_init
```

لا تشغّل compose الخاص بـPostgreSQL والآخر على المنفذ نفسه في الوقت نفسه. فحص الصحة يقرأ Firestore بالفعل، وقد يتأخر بدء الواجهة حتى إعداد القاعدة والصلاحيات. لم يُبن هذا المسار في الحاويات محليًا.

## نقل بيانات القسم الموجودة

لا تشغّل `firebase_init` أولًا إذا أردت ترحيل قاعدة SQL التي تحتوي المدير والملفات إلى وجهة فارغة. احتفظ بنسخة محلية آمنة أولًا. اضبط `DATABASE_URL` على قاعدة المصدر، ومتغيرات مشروع Firebase والاعتماد. افحص المصدر محليًا:

```powershell
python -m app.firestore_migrate
```

هذا جرد فقط لا يتصل بـFirebase ولا يرفع بيانات. بعد التأكد من الوجهة والأعداد:

```powershell
python -m app.firestore_migrate --apply
```

الأمر يرفض وجهة غير فارغة، ولا يدمج حسابات أو يكتب فوق بيانات موجودة. حد النقل الذري الحالي 450 وثيقة إجمالًا و750 KB لكل وثيقة. إن تجاوزت البيانات الحد يتوقف قبل النقل، ويحتاج النقل الكبير أداة تقسيم مجرّبة. لا يحذف المصدر ولا ينقل المرفقات؛ حافظ على ملفاتها وإعداد مسارها.

المجموعات تستخدم بادئة `ba_dms_`، ويمكن تغييرها بمتغير `FIREBASE_COLLECTION_PREFIX`. لا توجد مزامنة ثنائية بين قاعدتين بعد النقل. اختر قاعدة تشغيل واحدة واحتفظ بالقديمة نسخة احتياطية مقفلة.

نسخة محلية يدوية دون خدمات نسخ مدفوعة، بعد إيقاف الكتابة أثناء اللقطة:

```powershell
python -m app.firestore_backup export .local/department.backup.json
```

للاستعادة إلى وجهة اختبار فارغة ومع ضبط اعتماد تلك الوجهة:

```powershell
python -m app.firestore_backup restore .local/department.backup.json
```

تحتوي النسخة معلومات شخصية وتجزئات كلمات مرور، فاحفظها في مكان محمي خارج Git والمشاركة. انسخ المرفقات منفصلة. الاستعادة تخضع لحد 450 وثيقة ولا تكتب فوق بيانات. لم تُجر تجربة نسخة/استعادة سحابية حقيقية هنا.

## الاختبار والحدود

`MemoryStore` بديل عقد اختبارات فقط ولا يُختار في إعداد النشر. يمكن استخدام Firebase Emulator بعد تثبيت أدواته الرسمية، مع `FIRESTORE_EMULATOR_HOST` و`ALLOW_FIRESTORE_EMULATOR=1` بصورة صريحة، لكن المحاكي لم يكن متاحًا في هذا التحقق.

المعاملات تكتب الوثائق المتغيرة فقط وتتحقق من العلاقات قبل الحفظ. التبليغ الواحد محدود بـ400 مستلم والمعاملة بـ450 وثيقة متغيرة، وحجم الوثيقة مقيد بأقل من حد Firestore. الجدول والمرفقات الكبيرة تستلزم مراجعة الحجم والسياسة. لا ميزات PITR أو نسخ احتياطي سحابي مدفوع ضمن التنفيذ.
