# استخدم صورة Python مستقرة ومجربة
FROM python:3.11-slim

# ضبط المجلد الرئيسي
WORKDIR /app

# تثبيت الأدوات الأساسية لتجنب أخطاء البناء
RUN apt-get update && apt-get install -y build-essential gcc g++

# نسخ الملفات إلى الحاوية
COPY . .

# تحديث pip وتثبيت المتطلبات
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# تعيين المنفذ الافتراضي لـ Render
EXPOSE 10000

# تشغيل التطبيق باستخدام gunicorn
CMD gunicorn main:app --bind 0.0.0.0:${PORT:-10000}
