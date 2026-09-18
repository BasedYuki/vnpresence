# الخطوات الباقية

- [x] ملفات المشروع في `K:\Vn discord presence`
- [x] Discord Application ID (`1550577971448778872`) متحط في `src/vnpresence/config.py`
- [ ] تغيير اسم فولدر `github` إلى `.github`
- [ ] تجربة محلية
- [ ] الرفع على GitHub
- [ ] أول Release فيه `.exe`

---

## 1) غيّر اسم الفولدر إلى `.github`

الفولدر اسمه دلوقتي `github` من غير نقطة، وبكده GitHub Actions **مش هتشتغل**.
ويندوز Explorer بيرفض الأسماء اللي بتبدأ بنقطة، فاستخدم الـ Terminal بتاع
VS Code (`` Ctrl+` ``):

```powershell
cd "K:\Vn discord presence"
Rename-Item github .github
```

أو من شجرة الملفات في VS Code: كليك يمين على `github` → Rename → `.github`.

اتأكد إن النتيجة كده:

```
.github/workflows/ci.yml
.github/workflows/release.yml
.github/ISSUE_TEMPLATE/...
.github/pull_request_template.md
```

## 2) جرّبه محليًا

```powershell
cd "K:\Vn discord presence"
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

لو ظهر خطأ execution policy عند `activate`:

```powershell
Set-ExecutionPolicy -Scope Process RemoteSigned
```

بعدين، وDiscord مفتوح:

```powershell
vnpresence doctor
vnpresence add "D:\VN\<لعبتك>\game.exe"
vnpresence play <الـ id اللي طلع لك>
```

`doctor` المفروض يقول `discord : connected`. الأزرار مابتظهرش لصاحب الحساب
نفسه — اتأكد منها من حساب تاني.

## 3) ارفعه على GitHub

```powershell
cd "K:\Vn discord presence"
git init -b main
git add .
git commit -m "VNPresence 0.1.0 - Discord Rich Presence for visual novels"
```

مع GitHub CLI (بيعمل الريبو لوحده):

```powershell
gh auth login
gh repo create vnpresence --public --source=. --remote=origin --push
```

أو يدوي — اعمل ريبو فاضي اسمه `vnpresence` من <https://github.com/new>
(من غير README ولا .gitignore) وبعدين:

```powershell
git remote add origin https://github.com/BasedYuki/vnpresence.git
git push -u origin main
```

## 4) أول Release

```powershell
git tag v0.1.0
git push origin v0.1.0
```

الـ workflow هيبني `VNPresence.exe` على ويندوز ويعلّقه في صفحة Releases خلال
٣-٥ دقايق.

> job الـ `pypi` في `release.yml` محتاج environment اسمه `pypi` في إعدادات
> الريبو (Trusted Publishing). لو مش عايز تنشر على PyPI دلوقتي، امسح الـ job ده.

## ملاحظات

- الـ Application ID مش سر — عادي يتنشر في الريبو.
- كل اللينكات في الريبو على `BasedYuki/vnpresence`. لو غيّرت اسم الريبو، عدّلها
  في `README.md` و`pyproject.toml` و`src/vnpresence/vndb.py` (الـ User-Agent).
- `.gitignore` جاهز، فـ `.venv/` و`__pycache__/` مش هيترفعوا.
